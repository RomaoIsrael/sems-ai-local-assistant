"""Integración con el protocolo HTTP de Ollama mediante un servidor LOCAL simulado.

Esto verifica el cliente, el streaming, los embeddings, la búsqueda híbrida y la
validación de respuestas de IA. NO evalúa la calidad de un modelo real: esa
evaluación debe hacerse en el equipo destino con Ollama instalado
(ver docs/MANUAL_TECNICO.md, sección Evaluación).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sems_ai.compliance.gap_analysis import GapAnalyzer
from sems_ai.llm.ollama_client import OllamaClient
from sems_ai.rag.answer import AnswerEngine
from sems_ai.rag.retriever import Retriever
from sems_ai.rag.text_utils import stems

VOCAB = sorted(stems("auditar gestores ambientales inventario desechos almacenamiento cubeto manifiesto "
                     "transporte capacitación personal evidencias anual"))


def fake_vec(text: str) -> list[float]:
    s = stems(text)
    return [1.0 if v in s else 0.0 for v in VOCAB] + [0.01]


class Handler(BaseHTTPRequestHandler):
    chat_reply = ""

    def log_message(self, *a):
        pass

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "modelo-prueba:latest"}, {"name": "embed-prueba:latest"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/embed":
            self._json({"embeddings": [fake_vec(t) for t in body["input"]]})
        elif self.path == "/api/chat":
            reply = type(self).chat_reply
            if body.get("stream"):
                self.send_response(200)
                self.end_headers()
                for i in range(0, len(reply), 10):
                    self.wfile.write((json.dumps({"message": {"content": reply[i:i + 10]}, "done": False}) + "\n").encode())
                self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
            else:
                self._json({"message": {"content": reply}})


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def client(url):
    return OllamaClient(url, "modelo-prueba", "embed-prueba", timeout=10)


def test_status_and_stream(server, ctx):
    c = client(server)
    st = c.status()
    assert st.available and "modelo-prueba" in st.message
    Handler.chat_reply = "Respuesta de prueba en streaming con varios fragmentos."
    tokens = []
    out = c.chat("s", "u", on_token=tokens.append)
    assert out == Handler.chat_reply and len(tokens) > 3
    assert not OllamaClient(server, "otro-modelo").status().available


def test_semantic_hybrid_search(server, ctx, loaded):
    c = client(server)
    r = Retriever(ctx.db, c, semantic=True)
    n = r.index_embeddings()
    assert n == ctx.repository.stats()["fragmentos"]
    hits = r.search("auditar gestores ambientales anual", k=3)
    assert hits and hits[0].doc_code == "TEST-STD-001"
    assert any(h.method in ("semántica", "híbrida") for h in hits)


def test_rag_with_llm_streaming_and_validation(server, ctx, loaded):
    c = client(server)
    Handler.chat_reply = ("[REQUISITO DOCUMENTADO] El operador deberá auditar anualmente a los gestores ambientales "
                          "(numeral 1.4) [S1].\nIncertidumbres: no se identificó responsable.")
    eng = AnswerEngine(ctx.db, Retriever(ctx.db, c), c)
    toks = []
    ans = eng.ask("auditar gestores ambientales", on_token=toks.append)
    assert ans.mode == "llm" and ans.model == "modelo-prueba" and toks
    assert ans.warnings == []


def test_gap_llm_rejects_invented_quote(server, ctx, loaded):
    c = client(server)
    Handler.chat_reply = json.dumps({"result": "Cubierto documentalmente", "fragment": 1,
                                     "evidence_quote": "Se auditará a los gestores cada seis meses.",
                                     "gap": "", "recommendation": "", "justification": "x", "confidence": "Media"})
    ga = GapAnalyzer(ctx.db, c)
    aid = ga.run(loaded["std"].version_id, loaded["plan"].version_id)
    items = ga.items(aid)
    assert all(i["result"] == "Requiere validación adicional" for i in items)
    assert all("descartada" in i["justification"] for i in items)


def test_gap_llm_accepts_literal_quote(server, ctx, loaded):
    c = client(server)
    Handler.chat_reply = json.dumps({"result": "Cubierto documentalmente", "fragment": 1,
                                     "evidence_quote": "mantiene un inventario actualizado de los desechos generados",
                                     "gap": "", "recommendation": "", "justification": "Cita literal.",
                                     "confidence": "Alta"})
    ga = GapAnalyzer(ctx.db, c)
    items = ga.items(ga.run(loaded["std"].version_id, loaded["plan"].version_id))
    inv = next(i for i in items if i["numeral"] == "1.2")
    assert inv["result"] == "Cubierto documentalmente"
    assert inv["confidence"] == "Baja"  # "Alta" no se acepta sin revisión humana
    assert inv["justification"].startswith("[Análisis generado por IA local")
