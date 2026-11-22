"""Cliente mínimo para Ollama ejecutándose LOCALMENTE.

Solo se aceptan URLs de bucle local (127.0.0.1 / localhost / ::1). Si el usuario
configura un host remoto, el cliente se niega a conectarse: los documentos y
consultas nunca salen del equipo. Se usa ``urllib`` de la biblioteca estándar.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

from sems_ai.security.network_guard import is_local_url


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMStatus:
    available: bool
    message: str
    models: list[str]


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5:7b-instruct",
                 embedding_model: str = "bge-m3", timeout: int = 300, temperature: float = 0.1):
        if not is_local_url(base_url):
            raise ValueError("Por seguridad, SEMS AI solo admite un servidor Ollama local (127.0.0.1/localhost).")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.temperature = temperature

    # ------------------------------------------------------------ HTTP
    def _post(self, path: str, payload: dict, timeout: int | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:  # noqa: S310 (solo local)
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise LLMUnavailable(f"No se pudo contactar con Ollama en {self.base_url}: {exc}") from exc

    def status(self) -> LLMStatus:
        try:
            req = urllib.request.Request(self.base_url + "/api/tags")
            with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            return LLMStatus(False, f"Ollama no disponible ({type(exc).__name__}). Funciones de búsqueda activas.", [])
        models = [m.get("name", "") for m in data.get("models", [])]
        if not any(m == self.model or m.split(":")[0] == self.model.split(":")[0] for m in models):
            return LLMStatus(False, f"Ollama activo, pero el modelo '{self.model}' no está instalado.", models)
        return LLMStatus(True, f"Modelo local activo: {self.model}", models)

    def has_embedding_model(self) -> bool:
        st = self.status()
        return any(m.split(":")[0] == self.embedding_model.split(":")[0] for m in st.models)

    # ------------------------------------------------------------ generación
    def chat(self, system: str, user: str, on_token: Callable[[str], None] | None = None,
             cancel: Callable[[], bool] | None = None, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": on_token is not None,
            "options": {"temperature": self.temperature, "num_ctx": 8192},
        }
        if json_mode:
            payload["format"] = "json"
        if on_token is None:
            return self._post("/api/chat", payload).get("message", {}).get("content", "")
        out = []
        for piece in self._stream("/api/chat", payload, cancel):
            out.append(piece)
            on_token(piece)
        return "".join(out)

    def _stream(self, path: str, payload: dict, cancel=None) -> Iterator[str]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                for line in r:
                    if cancel and cancel():
                        break
                    if not line.strip():
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    yield obj.get("message", {}).get("content", "")
                    if obj.get("done"):
                        break
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise LLMUnavailable(f"Conexión con Ollama interrumpida: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        res = self._post("/api/embed", {"model": self.embedding_model, "input": texts})
        vecs = res.get("embeddings")
        if not vecs:
            raise LLMUnavailable("Ollama no devolvió embeddings (¿modelo de embeddings instalado?).")
        return vecs
