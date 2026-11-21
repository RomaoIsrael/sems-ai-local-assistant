"""Acceso a SQLite: conexiones por hilo, migraciones y utilidades."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

DEFAULT_CATEGORIES = [
    "Legislación ambiental ecuatoriana",
    "Estándares corporativos",
    "Procedimientos corporativos",
    "Procedimientos locales",
    "Planes de gestión",
    "Permisos y autorizaciones",
    "Estudios de impacto ambiental",
    "Planes de manejo ambiental",
    "Auditorías",
    "Evidencias",
    "Contratos",
    "Manuales técnicos",
    "Documentación QA/QC",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """Fábrica de conexiones SQLite. Cada operación abre su propia conexión,
    lo que permite usarla desde hilos de trabajo en segundo plano."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
        with self.connect() as c:
            c.executescript(schema)
            row = c.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                c.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            for name in DEFAULT_CATEGORIES:
                c.execute("INSERT OR IGNORE INTO categories(name, builtin) VALUES (?, 1)", (name,))

    # ------------- utilidades -------------
    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.connect() as c:
            return c.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self.connect() as c:
            return c.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def log(self, action: str, entity: str = "", entity_id: object = "", details: str = "",
            username: str | None = None) -> None:
        self.execute(
            "INSERT INTO audit_log(ts, username, action, entity, entity_id, details) VALUES (?,?,?,?,?,?)",
            (now_iso(), username or "", action, entity, str(entity_id), details),
        )
