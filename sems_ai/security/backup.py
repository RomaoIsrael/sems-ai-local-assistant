"""Respaldo y recuperación con verificación de integridad y cifrado opcional.

Formato:
- ``.zip``: respaldo sin cifrar (manifest.json con SHA-256 de cada archivo).
- ``.semsbak``: el mismo ZIP cifrado con Fernet (AES-128-CBC + HMAC-SHA256),
  clave derivada de la contraseña con PBKDF2-HMAC-SHA256 (600 000 iteraciones).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from sems_ai.config.settings import Settings

MAGIC = b"SEMSBAK1"
ITER = 600_000


class BackupError(Exception):
    pass


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def create_backup(settings: Settings, password: str | None = None, dest_dir: Path | None = None) -> Path:
    dest_dir = Path(dest_dir or settings.backups_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    buf = io.BytesIO()
    manifest = {"created_at": stamp, "format": 1, "files": {}}
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "sems_ai.db"
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(db_copy)
        with dst:
            src.backup(dst)  # copia consistente aunque la base esté en uso
        src.close()
        dst.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            def add(path: Path, arc: str):
                data = path.read_bytes()
                manifest["files"][arc] = hashlib.sha256(data).hexdigest()
                zf.writestr(arc, data)

            add(db_copy, "sems_ai.db")
            cfg = Settings.config_file(settings.base)
            if cfg.exists():
                add(cfg, "config.json")
            for f in sorted(settings.vault_dir.rglob("*")):
                if f.is_file():
                    add(f, "vault/" + f.relative_to(settings.vault_dir).as_posix())
            zf.writestr("manifest.json", json.dumps(manifest, indent=1))
    data = buf.getvalue()
    if password:
        from cryptography.fernet import Fernet

        salt = os.urandom(16)
        out = dest_dir / f"sems_ai_respaldo_{stamp}.semsbak"
        out.write_bytes(MAGIC + salt + Fernet(_key(password, salt)).encrypt(data))
    else:
        out = dest_dir / f"sems_ai_respaldo_{stamp}.zip"
        out.write_bytes(data)
    return out


def _open(path: Path, password: str | None) -> zipfile.ZipFile:
    raw = Path(path).read_bytes()
    if raw.startswith(MAGIC):
        if not password:
            raise BackupError("El respaldo está cifrado: indique la contraseña.")
        from cryptography.fernet import Fernet, InvalidToken

        salt = raw[len(MAGIC):len(MAGIC) + 16]
        try:
            raw = Fernet(_key(password, salt)).decrypt(raw[len(MAGIC) + 16:])
        except InvalidToken as exc:
            raise BackupError("Contraseña incorrecta o respaldo alterado.") from exc
    try:
        return zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise BackupError("Respaldo dañado.") from exc


def verify_backup(path: Path, password: str | None = None) -> dict:
    with _open(path, password) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        bad = [arc for arc, h in manifest["files"].items() if hashlib.sha256(zf.read(arc)).hexdigest() != h]
    if bad:
        raise BackupError(f"Archivos alterados en el respaldo: {bad[:5]}")
    return manifest


def restore_backup(path: Path, target_base: Path, password: str | None = None, overwrite: bool = False) -> Path:
    """Restaura en ``target_base``. Si existe una base de datos y no se autoriza
    sobrescribir, se aborta. Si se autoriza, el contenido previo se mueve a una
    carpeta ``_previo_<fecha>`` (no se elimina)."""
    manifest = verify_backup(path, password)
    target_base = Path(target_base)
    if (target_base / "sems_ai.db").exists():
        if not overwrite:
            raise BackupError("El destino ya contiene datos. Confirme la restauración (overwrite=True).")
        prev = target_base.with_name(target_base.name + "_previo_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.move(str(target_base), str(prev))
    target_base.mkdir(parents=True, exist_ok=True)
    with _open(path, password) as zf:
        for arc in manifest["files"]:
            p = (target_base / arc).resolve()
            if not str(p).startswith(str(target_base.resolve())):
                raise BackupError(f"Ruta insegura en el respaldo: {arc}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(zf.read(arc))
            if arc.startswith("vault/"):
                os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return target_base
