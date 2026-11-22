"""Configuración local de SEMS AI.

La configuración se guarda en un JSON dentro del directorio de datos del usuario.
Nunca se descarga configuración desde internet.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def default_data_dir() -> Path:
    """Directorio de datos: %LOCALAPPDATA%\\SEMS_AI en Windows, ~/.sems_ai en otros."""
    env = os.environ.get("SEMS_AI_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "SEMS_AI"
    return Path.home() / ".sems_ai"


@dataclass
class Settings:
    data_dir: str = ""
    language: str = "es"  # "es" | "en"
    # --- LLM local (Ollama). Solo se permiten hosts locales. ---
    llm_enabled: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    embedding_model: str = "bge-m3"
    semantic_search_enabled: bool = False
    llm_timeout_s: int = 300
    llm_temperature: float = 0.1
    llm_context_chunks: int = 6
    # --- Seguridad ---
    block_outbound_network: bool = True  # bloquea conexiones no locales
    require_login: bool = False
    max_file_size_mb: int = 300
    max_zip_uncompressed_mb: int = 1024
    max_zip_ratio: int = 100
    max_zip_depth: int = 2
    # --- Búsqueda ---
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150
    min_relevance_score: float = 0.0  # umbral BM25 normalizado (0 = sin filtro adicional)
    # --- Salidas ---
    export_dir: str = ""
    author_name: str = "SEMS AI"
    author_initials: str = "SA"
    pdf_viewer_command: str = ""  # p.ej. "C:\\SumatraPDF.exe" -page {page} "{file}"
    # --- Auditoría ---
    ocr_enabled: bool = True
    tesseract_cmd: str = ""
    extra: dict = field(default_factory=dict)

    # ---------------- rutas derivadas ----------------
    @property
    def base(self) -> Path:
        return Path(self.data_dir) if self.data_dir else default_data_dir()

    @property
    def db_path(self) -> Path:
        return self.base / "sems_ai.db"

    @property
    def vault_dir(self) -> Path:
        return self.base / "vault"

    @property
    def exports_path(self) -> Path:
        return Path(self.export_dir) if self.export_dir else self.base / "exports"

    @property
    def backups_dir(self) -> Path:
        return self.base / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.base / "logs"

    def ensure_dirs(self) -> None:
        for p in (self.base, self.vault_dir, self.exports_path, self.backups_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    # ---------------- persistencia ----------------
    @classmethod
    def config_file(cls, base: Path | None = None) -> Path:
        return (base or default_data_dir()) / "config.json"

    @classmethod
    def load(cls, base: Path | None = None) -> "Settings":
        path = cls.config_file(base)
        s = cls()
        if base is not None:
            s.data_dir = str(base)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            known = {f.name for f in fields(cls)}
            for k, v in raw.items():
                if k in known:
                    setattr(s, k, v)
        if base is not None:
            s.data_dir = str(base)
        s.ensure_dirs()
        return s

    def save(self) -> Path:
        self.ensure_dirs()
        path = self.config_file(self.base)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
