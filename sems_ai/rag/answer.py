"""Motor de respuestas RAG con verificación de citas.

Flujo: consulta → recuperación → evaluación de pertinencia → (modelo local) →
validación posterior de citas, numerales y códigos → respuesta con fuentes.

Si no hay fragmentos pertinentes, la respuesta es literalmente
``NO_EVIDENCE`` y el modelo no se invoca.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from sems_ai.database.db import Database, now_iso
from sems_ai.rag.retriever import Hit, Retriever

NO_EVIDENCE = ("No se ha encontrado evidencia documental suficiente en el repositorio para confirmar "
               "este requisito.")

LABELS = ["REQUISITO DOCUMENTADO", "OBLIGACIÓN LEGAL VERIFICADA", "INTERPRETACIÓN TÉCNICA",
          "RECOMENDACIÓN", "BUENA PRÁCTICA", "PENDIENTE DE VALIDAR"]

SYSTEM_PROMPT = f"""Eres SEMS AI, asistente técnico para sistemas de gestión SEMS, HSE, ambiente y QA/QC
en operaciones petroleras. Trabajas EXCLUSIVAMENTE con los fragmentos documentales que se te entregan.

Reglas obligatorias:
1. Usa solo información contenida en las FUENTES. No uses conocimiento externo para afirmar requisitos.
2. Cada afirmación basada en documentos debe terminar con su cita en formato [S1], [S2]...
3. No inventes códigos de documentos, numerales, cláusulas, artículos, fechas, cifras ni nombres de normas.
   Solo menciona numerales que aparezcan literalmente en las fuentes.
4. Clasifica cada punto de la respuesta con una etiqueta al inicio, entre corchetes:
   {', '.join('[' + x + ']' for x in LABELS)}.
   - [REQUISITO DOCUMENTADO]: el texto de una fuente lo establece expresamente.
   - [OBLIGACIÓN LEGAL VERIFICADA]: SOLO si la fuente está marcada como "legal_verificada=sí".
   - [INTERPRETACIÓN TÉCNICA], [RECOMENDACIÓN], [BUENA PRÁCTICA]: análisis tuyo; indícalo claramente.
   - [PENDIENTE DE VALIDAR]: información incompleta o ambigua.
5. Si las fuentes no permiten responder, responde exactamente: "{NO_EVIDENCE}"
6. Termina con una sección "Incertidumbres:" que indique lo que no pudo confirmarse.
Responde en {{lang}}, de forma técnica y concisa."""


@dataclass
class Answer:
    query: str
    text: str
    mode: str  # llm | extractivo | sin_evidencia
    sources: list[Hit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    history_id: int | None = None

    def sources_payload(self) -> list[dict]:
        return [{"n": i + 1, "chunk_id": h.chunk_id, "document_id": h.document_id, "version_id": h.version_id,
                 "doc": h.doc_name, "code": h.doc_code, "revision": h.revision, "section": h.section,
                 "page": h.page, "location": h.location, "file": h.filename, "score": round(h.score, 4),
                 "coverage": round(h.term_coverage, 3), "method": h.method} for i, h in enumerate(self.sources)]


NUMERAL_RE = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d{1,3}){1,4})(?!\.?\d)")
CODE_RE = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]{1,8}){0,4}-[A-Z]{0,4}\d{1,5}[A-Z]?)\b")
CITE_RE = re.compile(r"\[S(\d+)\]")


def validate_answer(text: str, sources: list[Hit], known_codes: set[str]) -> list[str]:
    """Comprueba que citas, numerales y códigos de la respuesta estén respaldados."""
    warnings: list[str] = []
    if text.strip().startswith(NO_EVIDENCE[:60]):
        return warnings
    corpus = "\n".join(h.text for h in sources)
    for n in sorted({int(x) for x in CITE_RE.findall(text)}):
        if n < 1 or n > len(sources):
            warnings.append(f"La cita [S{n}] no corresponde a ninguna fuente recuperada.")
    for num in sorted(set(NUMERAL_RE.findall(text))):
        if not re.search(rf"(?<![\d.]){re.escape(num)}(?![\d])", corpus) and \
                not any(h.section and num in h.section for h in sources):
            warnings.append(f"El numeral/valor «{num}» no aparece en las fuentes recuperadas: no verificado.")
    src_codes = {h.doc_code for h in sources if h.doc_code} | set(CODE_RE.findall(corpus))
    for code in sorted(set(CODE_RE.findall(text))):
        if code not in src_codes:
            if code in known_codes:
                warnings.append(f"El código «{code}» existe en el repositorio pero no en las fuentes citadas.")
            else:
                warnings.append(f"El código «{code}» no existe en el repositorio: posible código inventado.")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 40]
    body = [s for s in sentences if not s.lower().startswith(("incertidumbres", "- incertidumbre"))]
    uncited = [s for s in body if not CITE_RE.search(s) and
               not re.search(r"\[(INTERPRETACI|RECOMENDACI|BUENA PR|PENDIENTE)", s)]
    if body and len(uncited) / len(body) > 0.5:
        warnings.append(f"{len(uncited)} de {len(body)} frases no tienen cita ni etiqueta de análisis: "
                        "riesgo de afirmaciones sin respaldo.")
    if not CITE_RE.search(text):
        warnings.append("La respuesta no contiene citas a las fuentes.")
    return warnings


class AnswerEngine:
    def __init__(self, db: Database, retriever: Retriever, llm=None, language: str = "es", k: int = 6,
                 min_coverage: float = 0.25, username: str = ""):
        self.db = db
        self.retriever = retriever
        self.llm = llm
        self.language = language
        self.k = k
        self.min_coverage = min_coverage
        self.username = username

    def _legal_verified(self, document_ids: set[int]) -> set[int]:
        if not document_ids:
            return set()
        rows = self.db.query(
            f"SELECT document_id FROM legal_instruments WHERE validity_status='Vigente (verificado)' AND "
            f"document_id IN ({','.join('?' * len(document_ids))})", tuple(document_ids))
        return {r["document_id"] for r in rows}

    def relevant(self, hits: list[Hit]) -> list[Hit]:
        out = []
        for h in hits:
            if h.method in ("semántica", "híbrida") and h.extra.get("rrf") is not None:
                if h.term_coverage >= self.min_coverage * 0.5 or h.method == "híbrida":
                    out.append(h)
            elif h.term_coverage >= self.min_coverage:
                out.append(h)
        return out

    def build_prompt(self, query: str, hits: list[Hit]) -> tuple[str, str]:
        verified = self._legal_verified({h.document_id for h in hits})
        blocks = []
        for i, h in enumerate(hits, start=1):
            meta = (f"[S{i}] documento={h.doc_name} | código={h.doc_code or 'sin código registrado'} | "
                    f"revisión={h.revision or 'no registrada'} | sección={h.section or 'no identificada'} | "
                    f"página={h.page or '-'} | categoría={h.category or '-'} | "
                    f"legal_verificada={'sí' if h.document_id in verified else 'no'}")
            blocks.append(meta + "\n" + h.text.strip())
        lang = "español" if self.language == "es" else "inglés"
        system = SYSTEM_PROMPT.replace("{lang}", lang)
        user = "FUENTES:\n\n" + "\n\n---\n\n".join(blocks) + f"\n\nCONSULTA: {query}"
        return system, user

    def ask(self, query: str, filters: dict | None = None, on_token: Callable[[str], None] | None = None,
            cancel: Callable[[], bool] | None = None, use_llm: bool = True) -> Answer:
        filters = filters or {}
        hits = self.retriever.search(query, k=self.k, **filters)
        hits = self.relevant(hits)
        if not hits:
            ans = Answer(query, NO_EVIDENCE, "sin_evidencia", [], [])
            return self._save(ans)
        known_codes = {r["doc_code"] for r in self.db.query("SELECT doc_code FROM documents WHERE doc_code IS NOT NULL")}
        if use_llm and self.llm is not None:
            system, user = self.build_prompt(query, hits)
            text = self.llm.chat(system, user, on_token=on_token, cancel=cancel)
            ans = Answer(query, text.strip(), "llm", hits, validate_answer(text, hits, known_codes),
                         getattr(self.llm, "model", ""))
        else:
            lines = ["Modo sin modelo de IA: se muestran los fragmentos documentales más pertinentes. "
                     "No se ha generado interpretación automática.", ""]
            for i, h in enumerate(hits, start=1):
                excerpt = h.snippet or h.text[:400]
                lines.append(f"[S{i}] {h.citation()}\n    «{excerpt.strip()}»")
            ans = Answer(query, "\n".join(lines), "extractivo", hits, [])
        return self._save(ans)

    def _save(self, ans: Answer) -> Answer:
        ans.history_id = self.db.execute(
            "INSERT INTO query_history(ts, username, query, answer, mode, model, sources_json, warnings_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now_iso(), self.username, ans.query, ans.text, ans.mode, ans.model,
             json.dumps(ans.sources_payload(), ensure_ascii=False), json.dumps(ans.warnings, ensure_ascii=False)))
        return ans

    def history(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM query_history ORDER BY id DESC LIMIT ?", (limit,))]
