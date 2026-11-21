"""Extracción de requisitos individuales a partir de un documento de referencia.

Método determinista (no usa IA): se identifican frases con verbos de obligación
("shall", "must", "deberá", "debe", "se requiere"...), recomendación ("should",
"se recomienda") o prohibición, y se asocian al numeral vigente más cercano en el
texto. Los numerales provienen siempre del propio documento; si no se identifica
uno, el campo queda vacío (nunca se inventa).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sems_ai.database.db import Database
from sems_ai.rag.text_utils import strip_accents

OBLIGATION_PATTERNS: list[tuple[str, str]] = [
    ("Prohibición", r"\b(shall not|must not|may not|no deber[aá]n?|se proh[ií]be|est[aá] prohibid[oa]|prohibited)\b"),
    ("Obligatorio", r"\b(shall|must|is required to|are required to|required to|deber[aá]n?|deben?|"
                    r"se requiere|es obligatori[oa]|ser[aá] obligatori[oa]|tiene[n]? que|ha[n]? de)\b"),
    ("Recomendado", r"\b(should|se recomienda|deber[ií]an?|es recomendable|is recommended|are recommended)\b"),
]
_COMPILED = [(t, re.compile(p, re.I)) for t, p in OBLIGATION_PATTERNS]

NUMERAL_LINE = re.compile(r"^\s*(?:(?:Secci[oó]n|Section|Art[ií]culo|Art\.|Numeral|Cl[aá]usula)\s+)?"
                          r"((?:\d{1,2}\.){0,5}\d{1,3})(?:\.|\)|-)?\s+(?=\S)", re.I)
SENT_SPLIT = re.compile(r"(?<=[.;:!?])\s+(?=[A-ZÁÉÍÓÚÑ0-9(•\-])")


@dataclass
class Requirement:
    req_code: str
    numeral: str | None
    page: int | None
    text: str
    obligation_type: str
    keyword: str
    chunk_id: int


def classify(sentence: str) -> tuple[str, str] | None:
    for typ, rx in _COMPILED:
        m = rx.search(sentence)
        if m:
            return typ, m.group(1)
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s.lower())).strip()


def extract_requirements(chunks: list[dict], code_prefix: str) -> list[Requirement]:
    """``chunks``: dicts con id, text, page, section (en orden)."""
    reqs: list[Requirement] = []
    seen: set[str] = set()
    numeral: str | None = None
    for ch in chunks:
        sec_num = None
        if ch.get("section"):
            m = NUMERAL_LINE.match(ch["section"])
            if m:
                sec_num = m.group(1)
        if sec_num and numeral is None:
            numeral = sec_num
        blocks: list[tuple[str | None, list[str]]] = []
        cur: list[str] = []
        cur_num = numeral
        for line in ch["text"].splitlines():
            m = NUMERAL_LINE.match(line)
            # Un numeral válido: contiene un punto (1.2) o es un número corto seguido de título/texto
            if m and ("." in m.group(1) or len(m.group(1)) <= 2) and not re.match(r"^\s*\d+\s*(%|kg|m|t)\b", line):
                if cur:
                    blocks.append((cur_num, cur))
                cur_num = m.group(1)
                cur = [line[m.end():]]
            else:
                cur.append(line)
        if cur:
            blocks.append((cur_num, cur))
        numeral = cur_num
        for num, lines in blocks:
            lines = [ln for ln in lines if ln.strip()]
            # La primera línea corta sin verbo de obligación ni punto final es el título del numeral
            if len(lines) > 1 and len(lines[0]) < 90 and not lines[0].rstrip().endswith((".", ";", ":")) \
                    and not classify(lines[0]):
                lines = lines[1:]
            text = re.sub(r"\s+", " ", " ".join(lines)).strip()
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # guiones de corte de línea
            for sent in SENT_SPLIT.split(text):
                sent = sent.strip(" •-\t")
                if len(sent) < 25 or len(sent) > 1500:
                    continue
                cl = classify(sent)
                if not cl:
                    continue
                key = _norm(sent)
                if key in seen:
                    continue
                seen.add(key)
                reqs.append(Requirement(f"{code_prefix}-R{len(reqs) + 1:03d}", num, ch.get("page"), sent,
                                        cl[0], cl[1], ch["id"]))
    return reqs


class RequirementService:
    def __init__(self, db: Database):
        self.db = db

    def extract_for_version(self, version_id: int, replace: bool = True) -> list[dict]:
        v = self.db.query_one("SELECT v.*, d.doc_code, d.name FROM document_versions v JOIN documents d"
                              " ON d.id=v.document_id WHERE v.id=?", (version_id,))
        if v is None:
            raise KeyError(f"Versión {version_id} inexistente")
        chunks = [dict(r) for r in self.db.query(
            "SELECT id, text, page, section FROM chunks WHERE version_id=? ORDER BY seq", (version_id,))]
        prefix = v["doc_code"] or f"DOC{v['document_id']}"
        reqs = extract_requirements(chunks, prefix)
        with self.db.connect() as c:
            if replace:
                used = c.execute("SELECT COUNT(*) n FROM compliance_items ci JOIN requirements r ON r.id=ci.requirement_id"
                                 " WHERE r.version_id=?", (version_id,)).fetchone()["n"]
                if used:
                    # requisitos ya usados en análisis: no se borran, se conservan
                    existing = c.execute("SELECT * FROM requirements WHERE version_id=? ORDER BY id",
                                         (version_id,)).fetchall()
                    return [dict(r) for r in existing]
                c.execute("DELETE FROM requirements WHERE version_id=?", (version_id,))
            for r in reqs:
                c.execute("INSERT INTO requirements(document_id, version_id, req_code, numeral, page, text,"
                          " obligation_type, keyword, chunk_id) VALUES (?,?,?,?,?,?,?,?,?)",
                          (v["document_id"], version_id, r.req_code, r.numeral, r.page, r.text, r.obligation_type,
                           r.keyword, r.chunk_id))
        return self.list(version_id)

    def list(self, version_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM requirements WHERE version_id=? ORDER BY id",
                                               (version_id,))]
