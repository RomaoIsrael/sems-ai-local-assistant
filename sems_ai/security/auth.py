"""Control de acceso local: usuarios, contraseñas PBKDF2 y permisos por rol."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sems_ai.database.db import Database, now_iso

ITERATIONS = 310_000

ROLES: dict[str, set[str]] = {
    "admin": {"*"},
    "auditor": {
        "doc.read", "doc.import", "doc.edit", "query", "compliance.run", "compliance.review",
        "word.review", "word.approve", "audit.edit", "legal.edit", "waste.edit", "export",
    },
    "editor": {"doc.read", "doc.import", "doc.edit", "query", "compliance.run", "word.review",
               "waste.edit", "export"},
    "lector": {"doc.read", "query", "export"},
}


class AuthError(Exception):
    pass


@dataclass
class User:
    username: str
    role: str

    def can(self, permission: str) -> bool:
        perms = ROLES.get(self.role, set())
        return "*" in perms or permission in perms


def _hash(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class AuthService:
    def __init__(self, db: Database):
        self.db = db

    def has_users(self) -> bool:
        return self.db.query_one("SELECT COUNT(*) n FROM users")["n"] > 0

    def create_user(self, username: str, password: str, role: str) -> None:
        if role not in ROLES:
            raise AuthError(f"Rol no válido: {role}")
        if len(password) < 10:
            raise AuthError("La contraseña debe tener al menos 10 caracteres.")
        if not username.strip():
            raise AuthError("Usuario vacío.")
        salt = secrets.token_bytes(16)
        try:
            self.db.execute(
                "INSERT INTO users(username, pw_hash, salt, iterations, role, created_at) VALUES (?,?,?,?,?,?)",
                (username.strip(), _hash(password, salt, ITERATIONS), salt.hex(), ITERATIONS, role, now_iso()),
            )
        except Exception as exc:  # sqlite3.IntegrityError
            raise AuthError(f"No se pudo crear el usuario: {exc}") from exc
        self.db.log("user.create", "user", username, f"role={role}")

    def authenticate(self, username: str, password: str) -> User:
        row = self.db.query_one("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),))
        if row is None:
            self.db.log("login.fail", "user", username)
            raise AuthError("Usuario o contraseña incorrectos.")
        expected = _hash(password, bytes.fromhex(row["salt"]), row["iterations"])
        if not hmac.compare_digest(expected, row["pw_hash"]):
            self.db.log("login.fail", "user", username)
            raise AuthError("Usuario o contraseña incorrectos.")
        self.db.log("login.ok", "user", username, username=username)
        return User(row["username"], row["role"])

    def list_users(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT username, role, active, created_at FROM users ORDER BY username")]
