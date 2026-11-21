import socket

import pytest

from sems_ai.rag.answer import NO_EVIDENCE, AnswerEngine, validate_answer
from sems_ai.rag.evaluation import run_evaluation
from sems_ai.security import network_guard


class FakeLLM:
    """Doble de prueba del modelo local: devuelve un texto fijo para verificar validaciones."""
    model = "fake"
    embedding_model = "fake-embed"

    def __init__(self, text):
        self.text = text

    def chat(self, system, user, on_token=None, cancel=None, json_mode=False):
        assert "FUENTES" in user
        return self.text


def test_fulltext_search_finds_page(ctx, loaded):
    hits = ctx.retriever().fulltext("auditar gestores ambientales", k=5)
    assert hits
    top = hits[0]
    assert top.doc_code == "TEST-STD-001" and top.page == 1
    assert "gestores" in top.text.lower()


def test_accent_insensitive(ctx, loaded):
    hits = ctx.retriever().fulltext("senalizacion cubeto contencion")
    assert hits and "cubeto" in hits[0].text


def test_no_evidence_message(ctx, loaded):
    eng = ctx.answer_engine(use_llm=False)
    ans = eng.ask("frecuencia de calibración de cromatógrafos de gases")
    assert ans.text == NO_EVIDENCE and ans.mode == "sin_evidencia"


def test_extractive_mode_without_llm(ctx, loaded):
    ans = ctx.answer_engine(use_llm=False).ask("¿Cada cuánto se debe auditar a los gestores ambientales?")
    assert ans.mode == "extractivo"
    assert "[S1]" in ans.text and "TEST-STD-001" in ans.text
    assert ctx.db.query_one("SELECT COUNT(*) n FROM query_history")["n"] == 1


def test_llm_invented_code_and_numeral_flagged(ctx, loaded):
    llm = FakeLLM("[REQUISITO DOCUMENTADO] Se debe auditar a los gestores según el numeral 9.9.9 de "
                  "XYZ-SEMS-SOP-999 [S1]. [REQUISITO DOCUMENTADO] Conservar evidencias 5 años según 1.4 [S7].")
    eng = AnswerEngine(ctx.db, ctx.retriever(), llm)
    ans = eng.ask("auditar gestores ambientales evidencias")
    w = " ".join(ans.warnings)
    assert "9.9.9" in w and "XYZ-SEMS-SOP-999" in w and "posible código inventado" in w
    assert "[S7]" in w  # cita inexistente
    assert "«1.4»" not in w  # numeral real presente en fuente


def test_llm_grounded_answer_has_no_warnings(ctx, loaded):
    llm = FakeLLM("[REQUISITO DOCUMENTADO] Según el numeral 1.4 de TEST-STD-001, el operador deberá auditar "
                  "anualmente a los gestores ambientales [S1].\nIncertidumbres: ninguna adicional.")
    ans = AnswerEngine(ctx.db, ctx.retriever(), llm).ask("auditar anualmente gestores ambientales")
    assert ans.warnings == [], ans.warnings


def test_validate_answer_no_citations():
    w = validate_answer("Esta es una afirmación larga sin ninguna cita documental que la respalde en absoluto.", [],
                        set())
    assert any("no contiene citas" in x for x in w)


def test_offline_guard_blocks_external(ctx):
    assert network_guard.is_enabled()
    with pytest.raises(network_guard.OfflineViolation):
        socket.create_connection(("93.184.216.34", 80), timeout=2)
    with pytest.raises(network_guard.OfflineViolation):
        socket.getaddrinfo("example.com", 443)
    # localhost permitido (puede rechazar la conexión, pero no por la política)
    s = socket.socket()
    try:
        s.settimeout(0.5)
        s.connect_ex(("127.0.0.1", 9))
    finally:
        s.close()


def test_llm_client_rejects_remote_host():
    from sems_ai.llm.ollama_client import OllamaClient

    with pytest.raises(ValueError):
        OllamaClient("http://api.example.com:11434")


def test_llm_absent_app_still_works(ctx, loaded):
    ctx.settings.llm_enabled = True
    ctx.settings.ollama_url = "http://127.0.0.1:9"  # puerto sin servicio
    assert ctx.llm() is None
    assert "no disponible" in ctx.llm_status().lower()
    ans = ctx.answer_engine().ask("inventario de desechos")
    assert ans.mode == "extractivo"


def test_evaluation_metrics(ctx, loaded):
    cases = [
        {"id": "Q1", "question": "auditoría anual a gestores ambientales", "expected_doc_codes": ["TEST-STD-001"],
         "expected_terms": ["gestores"], "expected_numerals": ["1.4"]},
        {"id": "Q2", "question": "calibración de cromatógrafos", "expect_no_evidence": True},
    ]
    s = run_evaluation(ctx.answer_engine(use_llm=False), cases)
    assert s.hit_rate == 1.0 and s.mrr == 1.0 and s.no_evidence_accuracy == 1.0
