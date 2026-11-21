"""Revisor inteligente de Word.

Flujo:
1. ``create_review``: registra el DOCX de origen (y su SHA-256).
2. ``propose_from_analysis``: genera propuestas a partir de un análisis de
   cumplimiento (requisitos parcial o no identificados). Cada propuesta queda en
   estado *pendiente* hasta que una persona la acepte o rechace.
3. ``decide``: aceptación/rechazo individual, con posibilidad de editar el texto.
4. ``generate``: crea una COPIA del original con solo las propuestas aceptadas,
   resaltadas en amarillo y con comentarios de Word; genera el registro de
   modificaciones (Excel). El original no se modifica nunca y no se sobrescriben
   archivos existentes.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import docx

from sems_ai.database.db import Database, now_iso
from sems_ai.document_processing.safety import sha256_file
from sems_ai.rag.text_utils import stems
from sems_ai.word_review import docx_editor as ed

CLASSIFICATIONS = ["Requisito", "Recomendación", "Validación pendiente"]
DECISIONS = ["pendiente", "aceptada", "rechazada"]


class ReviewError(Exception):
    pass


def build_comment(ch: dict) -> str:
    parts = [f"Motivo: {ch.get('reason') or '-'}",
             f"Requisito relacionado: {ch.get('requirement') or '-'}",
             f"Fuente documental: {ch.get('source_document') or '-'}",
             f"Numeral aplicable: {ch.get('numeral') or 'no identificado en la fuente'}",
             f"Justificación técnica: {ch.get('justification') or '-'}",
             f"Clasificación: {ch.get('classification')}"]
    return "\n".join(parts)


@dataclass
class GenerationResult:
    output_path: Path
    log_path: Path
    applied: int
    output_sha256: str


class WordReviewService:
    def __init__(self, db: Database, author: str = "SEMS AI", initials: str = "SA", username: str = ""):
        self.db = db
        self.author = author
        self.initials = initials
        self.username = username

    # ------------------------------------------------------------------ creación
    def create_review(self, source_path: Path | str, source_version_id: int | None = None,
                      analysis_id: int | None = None) -> int:
        p = Path(source_path)
        if p.suffix.lower() != ".docx":
            raise ReviewError("El revisor solo admite archivos .docx (convierta .doc a .docx previamente).")
        docx.Document(str(p))  # valida que se pueda abrir
        rid = self.db.execute(
            "INSERT INTO word_reviews(created_at, created_by, source_version_id, source_path, source_sha256,"
            " analysis_id) VALUES (?,?,?,?,?,?)",
            (now_iso(), self.username, source_version_id, str(p), sha256_file(p), analysis_id))
        self.db.log("word.review.create", "word_review", rid, p.name, self.username)
        return rid

    def review(self, review_id: int) -> dict:
        r = self.db.query_one("SELECT * FROM word_reviews WHERE id=?", (review_id,))
        if not r:
            raise ReviewError(f"Revisión {review_id} inexistente")
        return dict(r)

    def paragraphs(self, review_id: int) -> list[dict]:
        d = docx.Document(self.review(review_id)["source_path"])
        return [{"index": i, "text": p.text, "style": p.style.name if p.style is not None else "",
                 "heading": ed.is_heading(p)} for i, p in enumerate(ed.body_paragraphs(d))]

    # ------------------------------------------------------------------ propuestas
    def _anchor(self, paras: list[dict], section: str | None, req_text: str) -> int:
        """Último párrafo no vacío de la sección más pertinente (o del documento)."""
        headings = [p for p in paras if p["heading"] and p["text"].strip()]
        target = None
        if section:
            target = next((h for h in headings if h["text"].strip() == section.strip()), None)
            if target is None:
                target = next((h for h in headings if section.strip().startswith(h["text"].strip()[:30])), None)
        if target is None and headings:
            rs = stems(req_text)
            scored = [(len(rs & stems(h["text"])), h) for h in headings]
            best = max(scored, key=lambda t: t[0])
            if best[0] > 0:
                target = best[1]
        nonempty = [p for p in paras if p["text"].strip()]
        if not nonempty:
            return 0
        if target is None:
            return nonempty[-1]["index"]
        last = target["index"]
        for p in paras[target["index"] + 1:]:
            if p["heading"]:
                break
            if p["text"].strip():
                last = p["index"]
        return last

    def propose_from_analysis(self, review_id: int, analysis_id: int, llm=None,
                              results=("Parcialmente cubierto", "No identificado en el documento")) -> int:
        paras = self.paragraphs(review_id)
        items = self.db.query(f"SELECT * FROM compliance_items WHERE analysis_id=? AND result IN"
                              f" ({','.join('?' * len(results))}) ORDER BY id", (analysis_id, *results))
        n = 0
        for it in items:
            idx = self._anchor(paras, it["local_section"], it["req_text"] or "")
            classification = "Recomendación" if it["obligation_type"] == "Recomendado" else "Requisito"
            if llm is not None:
                text = self._draft_with_llm(llm, dict(it), paras[idx]["text"] if paras else "")
                classification = "Validación pendiente" if not text else classification
            else:
                text = ""
            if not text:
                text = (f"[TEXTO PROPUESTO — EDITAR ANTES DE ACEPTAR] Incorporar disposición para atender el "
                        f"requisito {it['ident']}: {it['req_text']}")
            reason = ("Requisito parcialmente cubierto en el documento local" if it["result"] == "Parcialmente cubierto"
                      else "Requisito no identificado en el documento local")
            self.add_change(review_id, "insert_after", idx, text, reason=reason,
                            requirement=f"{it['ident']}: {it['req_text']}", source_document=it["source"],
                            numeral=it["numeral"], justification=(it["gap"] or "") + " " + (it["justification"] or ""),
                            classification=classification, compliance_item_id=it["id"],
                            anchor_text=paras[idx]["text"][:200] if paras else "")
            n += 1
        return n

    def _draft_with_llm(self, llm, it: dict, anchor_text: str) -> str:
        system = ("Redactas texto para un plan/procedimiento local en español técnico. Usa solo el requisito "
                  "proporcionado; no inventes cifras, plazos, normas ni responsables que no estén en el requisito. "
                  "Donde falte un dato, escribe [COMPLETAR]. Devuelve solo el párrafo propuesto.")
        user = f"Requisito ({it['source']} numeral {it['numeral'] or 'n/i'}): {it['req_text']}\n\n" \
               f"Párrafo del documento después del cual se insertará: {anchor_text}"
        try:
            return "[Texto redactado por IA local — validar] " + llm.chat(system, user).strip()
        except Exception:
            return ""

    def add_change(self, review_id: int, action: str, paragraph_index: int, new_text: str, *, reason: str = "",
                   requirement: str = "", source_document: str = "", numeral: str | None = None,
                   justification: str = "", classification: str = "Validación pendiente",
                   compliance_item_id: int | None = None, anchor_text: str = "") -> int:
        if action not in ("insert_after", "append_to"):
            raise ReviewError(f"Acción no válida: {action}")
        if classification not in CLASSIFICATIONS:
            raise ReviewError(f"Clasificación no válida: {classification}")
        if not new_text.strip():
            raise ReviewError("El texto propuesto está vacío.")
        seq = self.db.query_one("SELECT COALESCE(MAX(seq),0)+1 n FROM word_review_changes WHERE review_id=?",
                                (review_id,))["n"]
        return self.db.execute(
            "INSERT INTO word_review_changes(review_id, seq, action, paragraph_index, anchor_text, new_text, reason,"
            " requirement, source_document, numeral, justification, classification, compliance_item_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (review_id, seq, action, paragraph_index, anchor_text, new_text, reason, requirement, source_document,
             numeral, justification.strip(), classification, compliance_item_id))

    def changes(self, review_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM word_review_changes WHERE review_id=? ORDER BY seq",
                                               (review_id,))]

    def decide(self, change_id: int, decision: str, user: str, new_text: str | None = None,
               classification: str | None = None) -> None:
        if decision not in DECISIONS:
            raise ReviewError(f"Decisión no válida: {decision}")
        if decision != "pendiente" and not user.strip():
            raise ReviewError("La aprobación requiere identificar al responsable.")
        ch = self.db.query_one("SELECT * FROM word_review_changes WHERE id=?", (change_id,))
        if ch is None:
            raise ReviewError("Cambio inexistente")
        text = new_text if new_text is not None else ch["new_text"]
        if decision == "aceptada" and "EDITAR ANTES DE ACEPTAR" in text:
            raise ReviewError("Edite el texto propuesto (plantilla) antes de aceptarlo.")
        if classification and classification not in CLASSIFICATIONS:
            raise ReviewError("Clasificación no válida")
        self.db.execute("UPDATE word_review_changes SET decision=?, decided_by=?, decided_at=?, new_text=?,"
                        " classification=COALESCE(?, classification) WHERE id=?",
                        (decision, user, now_iso(), text, classification, change_id))
        self.db.log("word.change.decide", "word_change", change_id, decision, user)

    # ------------------------------------------------------------------ generación
    def generate(self, review_id: int, output_dir: Path | str) -> GenerationResult:
        rv = self.review(review_id)
        src = Path(rv["source_path"])
        if not src.exists():
            raise ReviewError("No se encuentra el documento de origen.")
        if sha256_file(src) != rv["source_sha256"]:
            raise ReviewError("El documento de origen cambió desde que se creó la revisión (hash distinto).")
        accepted = [c for c in self.changes(review_id) if c["decision"] == "aceptada"]
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"{src.stem}_REVISADO_{stamp}.docx"
        k = 1
        while out.exists():
            out = out_dir / f"{src.stem}_REVISADO_{stamp}_{k}.docx"
            k += 1
        shutil.copy2(src, out)
        document = docx.Document(str(out))
        paras = ed.body_paragraphs(document)
        # aplicar de abajo hacia arriba para no desplazar índices
        for ch in sorted(accepted, key=lambda c: (c["paragraph_index"], c["seq"]), reverse=True):
            if ch["paragraph_index"] >= len(paras):
                raise ReviewError(f"Índice de párrafo fuera de rango en el cambio {ch['seq']}")
            anchor = paras[ch["paragraph_index"]]
            if ch["action"] == "insert_after":
                _, run = ed.insert_paragraph_after(anchor, ch["new_text"])
            else:
                run = ed.append_to_paragraph(anchor, ch["new_text"])
            ed.add_comment(document, [run], build_comment(ch), self.author, self.initials)
        document.save(str(out))
        if sha256_file(src) != rv["source_sha256"]:  # salvaguarda
            raise ReviewError("ERROR CRÍTICO: el original fue alterado durante la generación.")
        out_sha = sha256_file(out)
        log_path = self.export_change_log(review_id, out.with_name(out.stem + "_registro_cambios.xlsx"), out.name)
        self.db.execute("UPDATE word_reviews SET output_path=?, output_sha256=?, status='generado' WHERE id=?",
                        (str(out), out_sha, review_id))
        self.db.log("word.review.generate", "word_review", review_id, f"{out.name} cambios={len(accepted)}",
                    self.username)
        return GenerationResult(out, log_path, len(accepted), out_sha)

    def export_change_log(self, review_id: int, path: Path, output_name: str = "") -> Path:
        from sems_ai.excel.builder import WorkbookBuilder

        rv = self.review(review_id)
        rows = [[c["seq"], c["decision"], c["classification"], c["action"], c["paragraph_index"],
                 (c["anchor_text"] or "")[:200], c["new_text"], c["reason"], c["requirement"], c["source_document"],
                 c["numeral"], c["justification"], c["decided_by"], c["decided_at"]] for c in self.changes(review_id)]
        wb = WorkbookBuilder()
        ws = wb.sheet("Registro de modificaciones")
        wb.title_block(ws, "Registro de modificaciones — Revisión de Word", [
            ("Documento original", Path(rv["source_path"]).name), ("SHA-256 original", rv["source_sha256"]),
            ("Copia generada", output_name or "-"), ("Fecha", now_iso()),
            ("Nota", "Solo las modificaciones 'aceptada' se incorporan en la copia. El original no se modifica.")])
        wb.table(ws, ["N°", "Decisión", "Clasificación", "Acción", "Párrafo", "Texto ancla", "Texto incorporado",
                      "Motivo", "Requisito", "Fuente", "Numeral", "Justificación", "Decidido por", "Fecha decisión"],
                 rows, start_row=8, widths=[5, 11, 16, 12, 8, 40, 60, 30, 50, 20, 10, 50, 16, 18],
                 validations={2: ["pendiente", "aceptada", "rechazada"], 3: CLASSIFICATIONS}, table_name="Cambios")
        return wb.save(path)
