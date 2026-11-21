"""Evaluación de recuperación y respuestas con un conjunto de referencia.

Formato del archivo de evaluación (JSON):
[
  {"id": "Q1", "question": "...",
   "expected_doc_codes": ["SPM-SEMS-SOP-001"],     # documentos que deben recuperarse
   "expected_terms": ["gestor", "auditoría"],        # términos que deben estar en los fragmentos
   "expected_numerals": ["1.6.2"],                   # opcional
   "expect_no_evidence": false}
]
Las preguntas de referencia deben ser preparadas por el usuario a partir de los
documentos reales; la aplicación no genera respuestas de referencia por sí misma.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sems_ai.rag.answer import NO_EVIDENCE, AnswerEngine
from sems_ai.rag.text_utils import strip_accents


@dataclass
class EvalResult:
    id: str
    question: str
    retrieved_codes: list[str]
    hit_at_k: bool
    reciprocal_rank: float
    term_recall: float
    numeral_found: bool | None
    no_evidence_ok: bool | None
    citation_warnings: list[str] = field(default_factory=list)
    mode: str = ""


@dataclass
class EvalSummary:
    n: int
    hit_rate: float
    mrr: float
    mean_term_recall: float
    no_evidence_accuracy: float | None
    answers_with_warnings: int
    total_warnings: int
    results: list[EvalResult]

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "results"}
        d["results"] = [r.__dict__ for r in self.results]
        return d


def run_evaluation(engine: AnswerEngine, cases: list[dict] | Path, use_llm: bool = False) -> EvalSummary:
    if isinstance(cases, (str, Path)):
        cases = json.loads(Path(cases).read_text(encoding="utf-8"))
    results: list[EvalResult] = []
    for c in cases:
        ans = engine.ask(c["question"], use_llm=use_llm)
        codes = [h.doc_code or h.doc_name for h in ans.sources]
        expected = c.get("expected_doc_codes") or []
        rr = 0.0
        for i, code in enumerate(codes, start=1):
            if code in expected:
                rr = 1.0 / i
                break
        corpus = strip_accents(" ".join(h.text for h in ans.sources).lower())
        terms = c.get("expected_terms") or []
        tr = (sum(1 for t in terms if strip_accents(t.lower()) in corpus) / len(terms)) if terms else 1.0
        nums = c.get("expected_numerals") or []
        nf = all(n in corpus for n in nums) if nums else None
        ne = None
        if "expect_no_evidence" in c:
            ne = (ans.text == NO_EVIDENCE) == bool(c["expect_no_evidence"])
        results.append(EvalResult(c.get("id", ""), c["question"], codes, rr > 0 if expected else not codes, rr, tr,
                                  nf, ne, ans.warnings, ans.mode))
    n = len(results) or 1
    with_exp = [r for r, c in zip(results, cases) if c.get("expected_doc_codes")]
    ne_list = [r.no_evidence_ok for r in results if r.no_evidence_ok is not None]
    return EvalSummary(
        n=len(results),
        hit_rate=sum(r.hit_at_k for r in with_exp) / (len(with_exp) or 1),
        mrr=sum(r.reciprocal_rank for r in with_exp) / (len(with_exp) or 1),
        mean_term_recall=sum(r.term_recall for r in results) / n,
        no_evidence_accuracy=(sum(ne_list) / len(ne_list)) if ne_list else None,
        answers_with_warnings=sum(1 for r in results if r.citation_warnings),
        total_warnings=sum(len(r.citation_warnings) for r in results),
        results=results,
    )
