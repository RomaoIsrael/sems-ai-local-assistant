"""Recuperación de fragmentos: texto completo (SQLite FTS5/BM25) + semántica opcional.

La búsqueda de texto completo funciona siempre, sin modelo de IA. La búsqueda
semántica solo se activa si hay un modelo de embeddings local en Ollama y los
fragmentos han sido vectorizados (``index_embeddings``).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Callable

from sems_ai.database.db import Database
from sems_ai.rag.text_utils import fts_query, stems


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    version_id: int
    text: str
    page: int | None
    section: str | None
    location: str | None
    doc_name: str
    doc_code: str | None
    revision: str | None
    category: str | None
    filename: str
    score: float
    method: str
    snippet: str = ""
    term_coverage: float = 0.0
    extra: dict = field(default_factory=dict)

    def citation(self) -> str:
        parts = [self.doc_code or self.doc_name]
        if self.revision:
            parts.append(f"Rev. {self.revision}")
        if self.section:
            parts.append(f"§ {self.section[:80]}")
        if self.page:
            parts.append(f"pág. {self.page}")
        elif self.location:
            parts.append(self.location)
        return ", ".join(parts)


_BASE_SELECT = """
SELECT c.id chunk_id, c.document_id, c.version_id, c.text, c.page, c.section, c.location,
       d.name doc_name, d.doc_code, COALESCE(v.revision, d.revision) revision, cat.name category,
       v.original_filename filename
FROM chunks c
JOIN documents d ON d.id=c.document_id
JOIN document_versions v ON v.id=c.version_id
LEFT JOIN categories cat ON cat.id=d.category_id
"""


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"{dim}f", blob))


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Retriever:
    def __init__(self, db: Database, llm=None, semantic: bool = False):
        self.db = db
        self.llm = llm
        self.semantic = semantic

    def _filters(self, document_ids, version_ids, category_ids, current_only) -> tuple[str, list]:
        where, params = [], []
        if document_ids:
            where.append(f"c.document_id IN ({','.join('?' * len(document_ids))})")
            params += list(document_ids)
        if version_ids:
            where.append(f"c.version_id IN ({','.join('?' * len(version_ids))})")
            params += list(version_ids)
        if category_ids:
            where.append(f"d.category_id IN ({','.join('?' * len(category_ids))})")
            params += list(category_ids)
        if current_only and not version_ids:
            where.append("c.version_id = d.current_version_id")
        return (" AND " + " AND ".join(where)) if where else "", params

    def fulltext(self, query: str, k: int = 10, document_ids=None, version_ids=None, category_ids=None,
                 current_only: bool = True) -> list[Hit]:
        q = fts_query(query)
        if not q:
            return []
        flt, params = self._filters(document_ids, version_ids, category_ids, current_only)
        sql = (_BASE_SELECT.replace("FROM chunks c", "FROM chunks_fts f JOIN chunks c ON c.id=f.rowid") +
               " WHERE chunks_fts MATCH ?" + flt +
               " ORDER BY bm25(chunks_fts, 1.0, 0.5) LIMIT ?")
        sql = sql.replace("SELECT c.id chunk_id", "SELECT bm25(chunks_fts, 1.0, 0.5) rank, "
                                                  "snippet(chunks_fts, 0, '«', '»', ' … ', 24) snip, c.id chunk_id")
        rows = self.db.query(sql, tuple([q] + params + [k * 3]))
        qstems = stems(query)
        hits = []
        for r in rows:
            cstems = stems(r["text"])
            coverage = len(qstems & cstems) / len(qstems) if qstems else 0.0
            # bm25 en SQLite es negativo (menor = mejor) → puntuación positiva
            score = -float(r["rank"])
            hits.append(Hit(r["chunk_id"], r["document_id"], r["version_id"], r["text"], r["page"], r["section"],
                            r["location"], r["doc_name"], r["doc_code"], r["revision"], r["category"], r["filename"],
                            score, "texto", r["snip"], coverage))
        hits.sort(key=lambda h: (h.term_coverage, h.score), reverse=True)
        return hits[:k]

    def semantic_search(self, query: str, k: int = 10, document_ids=None, version_ids=None, category_ids=None,
                        current_only: bool = True) -> list[Hit]:
        if not (self.semantic and self.llm):
            return []
        qv = self.llm.embed([query])[0]
        flt, params = self._filters(document_ids, version_ids, category_ids, current_only)
        sql = _BASE_SELECT.replace("SELECT c.id chunk_id", "SELECT e.vector, e.dim, c.id chunk_id") + \
            " JOIN embeddings e ON e.chunk_id=c.id WHERE e.model=?" + flt
        rows = self.db.query(sql, tuple([self.llm.embedding_model] + params))
        scored = []
        qstems = stems(query)
        for r in rows:
            s = _cos(qv, _unpack(r["vector"], r["dim"]))
            cov = len(qstems & stems(r["text"])) / len(qstems) if qstems else 0.0
            scored.append(Hit(r["chunk_id"], r["document_id"], r["version_id"], r["text"], r["page"], r["section"],
                              r["location"], r["doc_name"], r["doc_code"], r["revision"], r["category"],
                              r["filename"], s, "semántica", r["text"][:240], cov))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def search(self, query: str, k: int = 8, **filters) -> list[Hit]:
        """Búsqueda híbrida mediante fusión de rangos recíprocos (RRF)."""
        ft = self.fulltext(query, k * 2, **filters)
        try:
            sem = self.semantic_search(query, k * 2, **filters)
        except Exception:
            sem = []
        if not sem:
            return ft[:k]
        fused: dict[int, tuple[float, Hit]] = {}
        for lst in (ft, sem):
            for rank, h in enumerate(lst):
                prev = fused.get(h.chunk_id)
                val = 1.0 / (60 + rank) + (prev[0] if prev else 0.0)
                if prev:
                    if prev[1].method != h.method:
                        prev[1].method = "híbrida"
                    fused[h.chunk_id] = (val, prev[1])
                else:
                    fused[h.chunk_id] = (val, h)
        ordered = sorted(fused.values(), key=lambda t: t[0], reverse=True)
        out = []
        for val, h in ordered[:k]:
            h.extra["rrf"] = val
            out.append(h)
        return out

    def index_embeddings(self, batch: int = 16, progress: Callable[[int, int, str], None] | None = None,
                         cancel: Callable[[], bool] | None = None) -> int:
        if not self.llm:
            raise RuntimeError("No hay modelo local para embeddings.")
        rows = self.db.query("SELECT c.id, c.text FROM chunks c LEFT JOIN embeddings e ON e.chunk_id=c.id"
                             " WHERE e.chunk_id IS NULL ORDER BY c.id")
        done = 0
        for i in range(0, len(rows), batch):
            if cancel and cancel():
                break
            part = rows[i:i + batch]
            vecs = self.llm.embed([r["text"][:4000] for r in part])
            with self.db.connect() as c:
                for r, v in zip(part, vecs):
                    c.execute("INSERT OR REPLACE INTO embeddings(chunk_id, model, dim, vector) VALUES (?,?,?,?)",
                              (r["id"], self.llm.embedding_model, len(v), _pack(v)))
            done += len(part)
            if progress:
                progress(done, len(rows), "Generando embeddings locales")
        return done
