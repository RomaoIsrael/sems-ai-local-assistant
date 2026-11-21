"""Contexto de aplicación: une configuración, base de datos y servicios."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sems_ai.config.settings import Settings
from sems_ai.database.db import Database
from sems_ai.security import network_guard


class AppContext:
    def __init__(self, settings: Settings | None = None, username: str = ""):
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        if self.settings.block_outbound_network:
            network_guard.enable()
        self.username = username
        self._setup_logging()
        self.db = Database(self.settings.db_path)
        self._llm = None
        self._llm_error = ""

    def _setup_logging(self) -> None:
        log = logging.getLogger("sems_ai")
        if not log.handlers:
            h = RotatingFileHandler(self.settings.logs_dir / "sems_ai.log", maxBytes=2_000_000, backupCount=3,
                                    encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            log.addHandler(h)
            log.setLevel(logging.INFO)

    # ------------------------------------------------------------ servicios
    @property
    def repository(self):
        from sems_ai.repository.service import RepositoryService

        return RepositoryService(self.db, self.settings, self.username)

    def llm(self):
        """Devuelve el cliente LLM si el modelo local está disponible; si no, None."""
        if not self.settings.llm_enabled:
            self._llm_error = "IA local desactivada en la configuración."
            return None
        from sems_ai.llm.ollama_client import OllamaClient

        try:
            client = OllamaClient(self.settings.ollama_url, self.settings.llm_model, self.settings.embedding_model,
                                  self.settings.llm_timeout_s, self.settings.llm_temperature)
        except ValueError as exc:
            self._llm_error = str(exc)
            return None
        st = client.status()
        self._llm_error = st.message
        return client if st.available else None

    def llm_status(self) -> str:
        self.llm()
        return self._llm_error

    def retriever(self, llm=None):
        from sems_ai.rag.retriever import Retriever

        return Retriever(self.db, llm, semantic=self.settings.semantic_search_enabled and llm is not None)

    def answer_engine(self, use_llm: bool = True):
        from sems_ai.rag.answer import AnswerEngine

        llm = self.llm() if use_llm else None
        return AnswerEngine(self.db, self.retriever(llm), llm, self.settings.language,
                            self.settings.llm_context_chunks, username=self.username)

    @property
    def export_dir(self) -> Path:
        p = self.settings.exports_path
        p.mkdir(parents=True, exist_ok=True)
        return p
