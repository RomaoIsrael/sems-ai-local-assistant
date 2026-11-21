"""Comparación de requisitos (documento de referencia) con un documento evaluado.

Resultado preliminar por requisito. La ausencia de texto NO se interpreta como
incumplimiento operativo: el resultado "No identificado en el documento" se
refiere solo a la cobertura documental. Toda conclusión requiere validación del
auditor o responsable designado (``review_status``).
"""
from __future__ import annotations

import json
import re
from typing import Callable

from sems_ai.compliance.requirements import RequirementService
from sems_ai.database.db import Database, now_iso
from sems_ai.rag.retriever import Retriever
from sems_ai.rag.text_utils import detect_language, keywords, stem, stems, strip_accents

RESULTS = [
    "Cubierto documentalmente",
    "Parcialmente cubierto",
    "No identificado en el documento",
    "No aplicable, pendiente de justificar",
    "Requiere validación adicional",
]
REVIEW_STATES = ["Pendiente de revisión", "Validado por auditor", "Modificado por auditor", "Rechazado por auditor"]
COVERED, PARTIAL = 0.60, 0.35


def _best_sentence(req_stems: set[str], text: str) -> tuple[str, float]:
    best, score = "", 0.0
    for s in re.split(r"(?<=[.;!?])\s+|\n+", text):
        if len(s.strip()) < 15:
            continue
        cov = len(req_stems & stems(s)) / len(req_stems) if req_stems else 0
        if cov > score:
            best, score = s.strip(), cov
    return best, score


class GapAnalyzer:
    def __init__(self, db: Database, llm=None, username: str = ""):
        self.db = db
        self.llm = llm
        self.username = username
        self.retriever = Retriever(db)

    def run(self, reference_version_id: int, evaluated_version_id: int, title: str = "",
            progress: Callable[[int, int, str], None] | None = None,
            cancel: Callable[[], bool] | None = None, include_recommended: bool = True) -> int:
        reqs = RequirementService(self.db).extract_for_version(reference_version_id)
        if not include_recommended:
            reqs = [r for r in reqs if r["obligation_type"] != "Recomendado"]
        ref = self.db.query_one("SELECT d.name, d.doc_code, COALESCE(v.revision, d.revision) rev FROM document_versions v"
                                " JOIN documents d ON d.id=v.document_id WHERE v.id=?", (reference_version_id,))
        ev = self.db.query_one("SELECT d.name, d.doc_code FROM document_versions v JOIN documents d"
                               " ON d.id=v.document_id WHERE v.id=?", (evaluated_version_id,))
        ref_text = " ".join(r["text"] for r in self.db.query("SELECT text FROM chunks WHERE version_id=? LIMIT 40",
                                                              (reference_version_id,)))
        ev_text = " ".join(r["text"] for r in self.db.query("SELECT text FROM chunks WHERE version_id=? LIMIT 40",
                                                             (evaluated_version_id,)))
        lang_ref, lang_ev = detect_language(ref_text), detect_language(ev_text)
        cross_lang = lang_ref != lang_ev and "desconocido" not in (lang_ref, lang_ev)
        method = "LLM local + verificación de evidencia" if self.llm else "Comparación léxica determinista"
        analysis_id = self.db.execute(
            "INSERT INTO compliance_analyses(created_at, created_by, title, reference_version_id, evaluated_version_id,"
            " method, notes) VALUES (?,?,?,?,?,?,?)",
            (now_iso(), self.username, title or f"{ref['doc_code'] or ref['name']} vs {ev['doc_code'] or ev['name']}",
             reference_version_id, evaluated_version_id, method,
             f"Idioma referencia={lang_ref}; idioma evaluado={lang_ev}" + (
                 "; idiomas distintos: la comparación léxica no es concluyente" if cross_lang and not self.llm else "")))
        source_label = ref["doc_code"] or ref["name"]
        if ref["rev"]:
            source_label += f" Rev. {ref['rev']}"
        local_label = ev["doc_code"] or ev["name"]
        for i, r in enumerate(reqs, start=1):
            if cancel and cancel():
                break
            if progress:
                progress(i - 1, len(reqs), f"Evaluando {r['req_code']}")
            item = self._evaluate(r, evaluated_version_id, cross_lang)
            item.update(analysis_id=analysis_id, requirement_id=r["id"], ident=r["req_code"], source=source_label,
                        numeral=r["numeral"], req_page=r["page"], req_text=r["text"],
                        obligation_type=r["obligation_type"], local_document=local_label)
            cols = list(item)
            self.db.execute(f"INSERT INTO compliance_items({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                            tuple(item[c] for c in cols))
        if progress:
            progress(len(reqs), len(reqs), "Análisis finalizado")
        self.db.log("compliance.run", "analysis", analysis_id, f"{len(reqs)} requisitos; método={method}",
                    self.username)
        return analysis_id

    # ------------------------------------------------------------------
    def _evaluate(self, req: dict, evaluated_version_id: int, cross_lang: bool) -> dict:
        hits = self.retriever.fulltext(req["text"], k=5, version_ids=[evaluated_version_id])
        req_stems = stems(req["text"])
        if self.llm is not None:
            if cross_lang or not hits:
                # en idiomas distintos FTS falla: se usan las primeras secciones como candidatos
                hits = hits or self._all_hits(evaluated_version_id)
            try:
                return self._evaluate_llm(req, hits[:4])
            except Exception as exc:  # el error se registra en el ítem, no se oculta
                base = self._evaluate_lexical(req, req_stems, hits, cross_lang)
                base["justification"] += f" | Evaluación con IA fallida: {exc}"
                return base
        return self._evaluate_lexical(req, req_stems, hits, cross_lang)

    def _all_hits(self, version_id: int):
        from sems_ai.rag.retriever import Hit

        rows = self.db.query("SELECT c.*, d.name, d.doc_code FROM chunks c JOIN documents d ON d.id=c.document_id"
                             " WHERE c.version_id=? ORDER BY seq LIMIT 8", (version_id,))
        return [Hit(r["id"], r["document_id"], r["version_id"], r["text"], r["page"], r["section"], r["location"],
                    r["name"], r["doc_code"], None, None, "", 0.0, "secuencial") for r in rows]

    def _evaluate_lexical(self, req: dict, req_stems: set[str], hits, cross_lang: bool) -> dict:
        best_hit, best_sent, best_cov, chunk_cov = None, "", 0.0, 0.0
        for h in hits:
            sent, cov = _best_sentence(req_stems, h.text)
            ccov = len(req_stems & stems(h.text)) / len(req_stems) if req_stems else 0
            combined = max(cov, ccov * 0.9)
            if combined > best_cov:
                best_hit, best_sent, best_cov, chunk_cov = h, sent, combined, ccov
        if cross_lang:
            result = "Requiere validación adicional"
            gap = ("El documento de referencia y el evaluado están en idiomas distintos; la comparación léxica no es "
                   "concluyente. Active el modelo local o revise manualmente.")
            conf = "Baja"
        elif best_cov >= COVERED:
            result, gap, conf = "Cubierto documentalmente", "", "Media"
        elif best_cov >= PARTIAL:
            result = "Parcialmente cubierto"
            conf = "Baja"
            present = stems(best_hit.text) if best_hit else set()
            missing = [w for w in dict.fromkeys(keywords(req["text"])) if stem(w) not in present][:10]
            gap = "Elementos del requisito no identificados en el texto local: " + ", ".join(missing)
        else:
            result = "No identificado en el documento"
            conf = "Media" if best_cov < 0.2 else "Baja"
            gap = "No se identificó en el documento evaluado una disposición equivalente al requisito."
        if result in ("Parcialmente cubierto", "No identificado en el documento"):
            rec = (f"Evaluar la incorporación en el documento local de una disposición que atienda el requisito "
                   f"{req['req_code']}" + (f" (numeral {req['numeral']})" if req["numeral"] else "") +
                   ", definiendo responsables, frecuencia y registros/evidencias asociados.")
            action = "Revisar y, si aplica, actualizar el documento local; validar con el responsable del proceso."
        elif result == "Requiere validación adicional":
            rec, action = "Revisión manual por el auditor.", "Validación humana del requisito."
        else:
            rec, action = "", "Verificar en campo la implementación (la cobertura documental no prueba la ejecución)."
        just = (f"Comparación léxica automática: {best_cov:.0%} de los términos clave del requisito aparecen en el "
                f"texto local mejor coincidente. Resultado preliminar; no constituye prueba de cumplimiento operativo "
                f"y requiere revisión humana.")
        return {
            "local_section": best_hit.section if best_hit else None,
            "local_page": best_hit.page if best_hit else None,
            "local_chunk_id": best_hit.chunk_id if best_hit else None,
            "evidence": (best_sent or (best_hit.text[:400] if best_hit else "")) if best_cov >= PARTIAL else "",
            "result": result, "gap": gap, "recommendation": rec, "justification": just,
            "proposed_action": action, "confidence": conf, "score": round(best_cov, 3),
        }

    def _evaluate_llm(self, req: dict, hits) -> dict:
        blocks = "\n\n".join(f"[L{i + 1}] sección={h.section or '-'} página={h.page or '-'}\n{h.text}"
                             for i, h in enumerate(hits))
        system = ("Eres un auditor documental. Compara un REQUISITO con FRAGMENTOS de un documento local. "
                  "Responde SOLO en JSON con las claves: result (uno de: " + "; ".join(RESULTS[:3] + RESULTS[4:]) +
                  "), fragment (número del fragmento L usado o 0), evidence_quote (cita LITERAL copiada del "
                  "fragmento, o vacío), gap, recommendation, justification, confidence (Baja|Media). "
                  "No inventes texto: evidence_quote debe aparecer exactamente en el fragmento. "
                  "La ausencia de texto no prueba incumplimiento operativo. Responde en español.")
        user = f"REQUISITO {req['req_code']} (numeral {req['numeral'] or 'no identificado'}):\n{req['text']}\n\n" \
               f"FRAGMENTOS DEL DOCUMENTO LOCAL:\n{blocks or '(sin fragmentos)'}"
        raw = self.llm.chat(system, user, json_mode=True)
        data = json.loads(raw)
        result = data.get("result") if data.get("result") in RESULTS else "Requiere validación adicional"
        quote = (data.get("evidence_quote") or "").strip()
        idx = int(data.get("fragment") or 0)
        hit = hits[idx - 1] if 0 < idx <= len(hits) else None
        warn = ""
        if quote:
            nq = re.sub(r"\s+", " ", strip_accents(quote.lower()))
            found = next((h for h in hits if nq[:200] in re.sub(r"\s+", " ", strip_accents(h.text.lower()))), None)
            if found is None:
                warn = " | ADVERTENCIA: la cita propuesta por la IA no se encontró literalmente en el documento; descartada."
                quote = ""
                result = "Requiere validación adicional"
            else:
                hit = found
        elif result in ("Cubierto documentalmente", "Parcialmente cubierto"):
            result = "Requiere validación adicional"
            warn = " | La IA indicó cobertura sin aportar cita literal."
        conf = data.get("confidence") if data.get("confidence") in ("Baja", "Media") else "Baja"
        return {
            "local_section": hit.section if hit else None, "local_page": hit.page if hit else None,
            "local_chunk_id": hit.chunk_id if hit else None, "evidence": quote, "result": result,
            "gap": data.get("gap", ""), "recommendation": data.get("recommendation", ""),
            "justification": "[Análisis generado por IA local — requiere validación] " +
                             str(data.get("justification", "")) + warn,
            "proposed_action": data.get("recommendation", ""), "confidence": conf, "score": None,
        }

    # ------------------------------------------------------------------ consulta y revisión
    def analyses(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT a.*, (SELECT COUNT(*) FROM compliance_items i WHERE i.analysis_id=a.id) n_items"
            " FROM compliance_analyses a ORDER BY a.id DESC")]

    def items(self, analysis_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM compliance_items WHERE analysis_id=? ORDER BY id",
                                               (analysis_id,))]

    def review(self, item_id: int, review_status: str, reviewer: str, result: str | None = None,
               notes: str = "") -> None:
        if review_status not in REVIEW_STATES:
            raise ValueError(f"Estado de revisión no válido: {review_status}")
        if result is not None and result not in RESULTS:
            raise ValueError(f"Resultado no válido: {result}")
        if review_status != "Pendiente de revisión" and not reviewer.strip():
            raise ValueError("La revisión humana requiere identificar al revisor.")
        sets = "review_status=?, reviewer=?, reviewed_at=?, reviewer_notes=?"
        params: list = [review_status, reviewer, now_iso(), notes]
        if result:
            sets += ", result=?"
            params.append(result)
        params.append(item_id)
        self.db.execute(f"UPDATE compliance_items SET {sets} WHERE id=?", tuple(params))
        self.db.log("compliance.review", "item", item_id, f"{review_status} result={result}", reviewer)

    def summary(self, analysis_id: int) -> dict[str, int]:
        out = {r: 0 for r in RESULTS}
        for row in self.db.query("SELECT result, COUNT(*) n FROM compliance_items WHERE analysis_id=? GROUP BY result",
                                 (analysis_id,)):
            out[row["result"]] = row["n"]
        return out
