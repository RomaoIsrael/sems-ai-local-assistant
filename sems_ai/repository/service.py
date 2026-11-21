"""Repositorio documental: importación, bóveda de originales, versiones e integridad.

Principios:
- El archivo original NUNCA se modifica: se copia a la bóveda (``vault``) con
  nombre basado en su SHA-256 y se marca como solo lectura.
- Una nueva revisión crea una nueva versión; las anteriores se conservan.
- Lo que no puede extraerse se marca como ``no_compatible`` / ``pendiente_ocr``.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from sems_ai.config.settings import Settings
from sems_ai.database.db import Database, now_iso
from sems_ai.document_processing import extractors as ex
from sems_ai.document_processing.chunker import chunk_segments
from sems_ai.document_processing.safety import (UnsafeFileError, inspect_file, safe_extract_zip,
                                                 sha256_file)

DOC_CODE_RE = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z0-9]{1,8}){0,4}-[A-Z]{0,4}\d{1,5}[A-Z]?)\b")
REV_RE = re.compile(r"\b(?:Rev(?:isi[oó]n)?\.?|Revision|Versi[oó]n)\s*[:#]?\s*([A-Z0-9]{1,4}(?:\.\d+)?)\b", re.I)

ProgressCb = Callable[[int, int, str], None]


class CancelledError(Exception):
    pass


@dataclass
class ImportOutcome:
    path: str
    status: str  # importado | nueva_version | duplicado | rechazado | error
    message: str = ""
    document_id: int | None = None
    version_id: int | None = None
    extraction_status: str | None = None
    flags: list[str] = field(default_factory=list)


class RepositoryService:
    def __init__(self, db: Database, settings: Settings, username: str = ""):
        self.db = db
        self.settings = settings
        self.username = username
        self.ocr = ex.OcrEngine(settings.tesseract_cmd) if settings.ocr_enabled else None

    # ------------------------------------------------------------ categorías
    def categories(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM categories ORDER BY builtin DESC, id")]

    def add_category(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Nombre de categoría vacío.")
        cid = self.db.execute("INSERT INTO categories(name, builtin) VALUES (?, 0)", (name,))
        self.db.log("category.create", "category", cid, name, self.username)
        return cid

    def category_id(self, name: str | None) -> int | None:
        if not name:
            return None
        row = self.db.query_one("SELECT id FROM categories WHERE name=?", (name,))
        return row["id"] if row else self.add_category(name)

    # ------------------------------------------------------------ bóveda
    def _store(self, src: Path, sha: str) -> Path:
        ext = src.suffix.lower()
        dest = self.settings.vault_dir / sha[:2] / f"{sha}{ext}"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            shutil.copy2(src, tmp)
            if sha256_file(tmp) != sha:
                tmp.unlink(missing_ok=True)
                raise IOError("La copia en la bóveda no coincide con el original (hash distinto).")
            os.replace(tmp, dest)
            os.chmod(dest, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        return dest

    # ------------------------------------------------------------ importación
    def import_paths(self, paths: Iterable[Path | str], category: str | None = None,
                     metadata: dict | None = None, progress: ProgressCb | None = None,
                     cancel: Callable[[], bool] | None = None) -> list[ImportOutcome]:
        files: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                files.extend(sorted(x for x in p.rglob("*") if x.is_file() and not x.name.startswith("~$")))
            elif p.is_file():
                files.append(p)
        results: list[ImportOutcome] = []
        for i, f in enumerate(files, start=1):
            if cancel and cancel():
                raise CancelledError("Importación cancelada por el usuario.")
            if progress:
                progress(i - 1, len(files), f"Procesando {f.name}")
            results.extend(self._import_any(f, category, metadata or {}, depth=0, cancel=cancel))
        if progress:
            progress(len(files), len(files), "Importación finalizada")
        return results

    def _import_any(self, f: Path, category, metadata, depth: int, cancel=None) -> list[ImportOutcome]:
        if f.suffix.lower() == ".zip":
            out = [self.import_file(f, category, metadata)]
            if out[0].status in ("rechazado", "error"):
                return out
            if depth >= self.settings.max_zip_depth:
                out[0].message += " | Anidamiento máximo de ZIP alcanzado; contenido no importado."
                return out
            with tempfile.TemporaryDirectory(prefix="sems_zip_") as tmp:
                try:
                    extracted = safe_extract_zip(f, Path(tmp), self.settings.max_zip_uncompressed_mb,
                                                 self.settings.max_zip_ratio)
                except UnsafeFileError as exc:
                    out[0].message += f" | Contenido no extraído: {exc}"
                    return out
                for x in extracted:
                    if cancel and cancel():
                        raise CancelledError("Importación cancelada por el usuario.")
                    md = dict(metadata)
                    md.setdefault("source", f"Contenido de {f.name}")
                    out.extend(self._import_any(x, category, md, depth + 1, cancel))
            return out
        return [self.import_file(f, category, metadata)]

    def import_file(self, path: Path | str, category: str | None = None, metadata: dict | None = None,
                    document_id: int | None = None) -> ImportOutcome:
        """Importa un archivo. Si ``document_id`` se indica, se registra como nueva versión."""
        path = Path(path)
        metadata = dict(metadata or {})
        try:
            report = inspect_file(path, self.settings.max_file_size_mb)
        except UnsafeFileError as exc:
            self.db.log("doc.reject", "file", path.name, str(exc), self.username)
            return ImportOutcome(str(path), "rechazado", str(exc))
        except OSError as exc:
            return ImportOutcome(str(path), "error", f"No se pudo leer el archivo: {exc}")
        sha = sha256_file(path)
        dup = self.db.query_one(
            "SELECT v.id, v.document_id FROM document_versions v WHERE v.sha256=?", (sha,))
        if dup:
            return ImportOutcome(str(path), "duplicado",
                                 "El mismo archivo (SHA-256 idéntico) ya existe en el repositorio.",
                                 dup["document_id"], dup["id"])
        try:
            stored = self._store(path, sha)
        except OSError as exc:
            return ImportOutcome(str(path), "error", f"No se pudo copiar a la bóveda: {exc}")

        result = ex.extract(stored, self.ocr)
        detected = self._detect_metadata(path, result)
        ts = now_iso()
        cat_id = self.category_id(category or metadata.get("category")) if document_id is None else None
        with self.db.connect() as c:
            if document_id is None:
                code = metadata.get("doc_code") or detected.get("doc_code")
                notes = metadata.get("notes") or ""
                if not metadata.get("doc_code") and detected.get("doc_code"):
                    notes = (notes + "\n" if notes else "") + (
                        f"Código '{detected['doc_code']}' detectado automáticamente en {detected['code_origin']}; "
                        "requiere verificación.")
                cur = c.execute(
                    """INSERT INTO documents(name, doc_code, category_id, area, doc_type, issuer, revision,
                       issue_date, effective_date, added_at, status, source, verifier, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (metadata.get("name") or path.stem, code, cat_id,
                     metadata.get("area"), metadata.get("doc_type"), metadata.get("issuer"),
                     metadata.get("revision") or detected.get("revision"), metadata.get("issue_date"),
                     metadata.get("effective_date"), ts, metadata.get("status") or "Pendiente de verificación",
                     metadata.get("source") or str(path.parent), metadata.get("verifier"), notes),
                )
                document_id = cur.lastrowid
                version_no = 1
                status = "importado"
            else:
                row = c.execute("SELECT COALESCE(MAX(version_no),0) n FROM document_versions WHERE document_id=?",
                                (document_id,)).fetchone()
                version_no = row["n"] + 1
                status = "nueva_version"
            cur = c.execute(
                """INSERT INTO document_versions(document_id, version_no, revision, original_filename, original_path,
                   stored_path, sha256, size_bytes, extension, imported_at, imported_by, extraction_status,
                   extraction_message, page_count, security_flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (document_id, version_no, metadata.get("revision") or detected.get("revision"), path.name, str(path),
                 str(stored.relative_to(self.settings.base)), sha, path.stat().st_size, path.suffix.lower(), ts,
                 self.username, result.status, result.message, result.page_count, ";".join(report.flags)),
            )
            version_id = cur.lastrowid
            for ch in chunk_segments(result.segments, self.settings.chunk_size_chars,
                                     self.settings.chunk_overlap_chars):
                c.execute("INSERT INTO chunks(version_id, document_id, seq, page, section, location, text)"
                          " VALUES (?,?,?,?,?,?,?)",
                          (version_id, document_id, ch.seq, ch.page, ch.section, ch.location, ch.text))
            c.execute("UPDATE documents SET current_version_id=? WHERE id=?", (version_id, document_id))
            if status == "nueva_version" and metadata.get("revision"):
                c.execute("UPDATE documents SET revision=? WHERE id=?", (metadata["revision"], document_id))
        self.db.log("doc.import" if status == "importado" else "doc.new_version", "document", document_id,
                    f"{path.name} sha256={sha} extraccion={result.status}", self.username)
        return ImportOutcome(str(path), status, result.message, document_id, version_id, result.status, report.flags)

    def _detect_metadata(self, path: Path, result: ex.ExtractionResult) -> dict:
        out: dict = {}
        m = DOC_CODE_RE.search(path.stem.upper().replace("_", "-"))
        if m:
            out["doc_code"], out["code_origin"] = m.group(1), "el nombre del archivo"
        else:
            head = result.text[:3000]
            m = DOC_CODE_RE.search(head)
            if m:
                out["doc_code"], out["code_origin"] = m.group(1), "el texto inicial del documento"
        m = REV_RE.search(result.text[:3000])
        if m:
            out["revision"] = m.group(1)
        return out

    # ------------------------------------------------------------ consultas
    def list_documents(self, category_id: int | None = None, text: str = "") -> list[dict]:
        sql = """SELECT d.*, c.name AS category, v.original_filename, v.extraction_status, v.sha256,
                 v.version_no, v.stored_path, v.page_count, v.security_flags, v.extension
                 FROM documents d LEFT JOIN categories c ON c.id=d.category_id
                 LEFT JOIN document_versions v ON v.id=d.current_version_id WHERE 1=1"""
        params: list = []
        if category_id:
            sql += " AND d.category_id=?"
            params.append(category_id)
        if text:
            like = f"%{text}%"
            sql += " AND (d.name LIKE ? OR d.doc_code LIKE ? OR d.revision LIKE ? OR d.issue_date LIKE ?" \
                   " OR v.original_filename LIKE ?)"
            params += [like] * 5
        sql += " ORDER BY d.added_at DESC, d.id DESC"
        return [dict(r) for r in self.db.query(sql, tuple(params))]

    def get_document(self, document_id: int) -> dict | None:
        rows = self.list_documents()
        for r in rows:
            if r["id"] == document_id:
                return r
        return None

    def versions(self, document_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM document_versions WHERE document_id=? ORDER BY version_no", (document_id,))]

    def version(self, version_id: int) -> dict | None:
        r = self.db.query_one(
            """SELECT v.*, d.name, d.doc_code, d.revision AS doc_revision FROM document_versions v
               JOIN documents d ON d.id=v.document_id WHERE v.id=?""", (version_id,))
        return dict(r) if r else None

    def stored_file(self, version_id: int) -> Path:
        v = self.version(version_id)
        if not v:
            raise KeyError(f"Versión {version_id} inexistente")
        return self.settings.base / v["stored_path"]

    METADATA_FIELDS = ("name", "doc_code", "area", "doc_type", "issuer", "revision", "issue_date",
                       "effective_date", "last_verified_at", "status", "source", "verifier", "notes")

    def update_metadata(self, document_id: int, changes: dict) -> None:
        sets, params = [], []
        for k, v in changes.items():
            if k == "category":
                sets.append("category_id=?")
                params.append(self.category_id(v))
            elif k in self.METADATA_FIELDS:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        params.append(document_id)
        self.db.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id=?", tuple(params))
        self.db.log("doc.update", "document", document_id, repr(changes), self.username)

    def add_relation(self, document_id: int, related_id: int, relation: str, notes: str = "") -> None:
        self.db.execute("INSERT OR IGNORE INTO document_relations(document_id, related_document_id, relation, notes)"
                        " VALUES (?,?,?,?)", (document_id, related_id, relation, notes))

    def relations(self, document_id: int) -> list[dict]:
        return [dict(r) for r in self.db.query(
            """SELECT r.relation, r.notes, d.id, d.name, d.doc_code FROM document_relations r
               JOIN documents d ON d.id=r.related_document_id WHERE r.document_id=?""", (document_id,))]

    def reprocess(self, version_id: int) -> str:
        """Vuelve a extraer el texto (p.ej. tras instalar OCR). Conserva el original."""
        path = self.stored_file(version_id)
        v = self.version(version_id)
        result = ex.extract(path, self.ocr)
        with self.db.connect() as c:
            c.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE version_id=?)",
                      (version_id,))
            c.execute("DELETE FROM chunks WHERE version_id=?", (version_id,))
            for ch in chunk_segments(result.segments, self.settings.chunk_size_chars,
                                     self.settings.chunk_overlap_chars):
                c.execute("INSERT INTO chunks(version_id, document_id, seq, page, section, location, text)"
                          " VALUES (?,?,?,?,?,?,?)",
                          (version_id, v["document_id"], ch.seq, ch.page, ch.section, ch.location, ch.text))
            c.execute("UPDATE document_versions SET extraction_status=?, extraction_message=?, page_count=?"
                      " WHERE id=?", (result.status, result.message, result.page_count, version_id))
        self.db.log("doc.reprocess", "version", version_id, result.status, self.username)
        return result.status

    # ------------------------------------------------------------ integridad
    def verify_integrity(self) -> list[dict]:
        """Recalcula el SHA-256 de cada original en la bóveda y lo compara con el registrado."""
        out = []
        for v in self.db.query("SELECT id, document_id, stored_path, sha256, original_filename FROM document_versions"):
            p = self.settings.base / v["stored_path"]
            if not p.exists():
                state = "FALTA"
            else:
                state = "OK" if sha256_file(p) == v["sha256"] else "ALTERADO"
            out.append({"version_id": v["id"], "document_id": v["document_id"],
                        "file": v["original_filename"], "estado": state})
        self.db.log("integrity.check", "vault", "", f"{sum(1 for o in out if o['estado'] != 'OK')} incidencias",
                    self.username)
        return out

    def stats(self) -> dict:
        q = self.db.query_one
        return {
            "documentos": q("SELECT COUNT(*) n FROM documents")["n"],
            "versiones": q("SELECT COUNT(*) n FROM document_versions")["n"],
            "fragmentos": q("SELECT COUNT(*) n FROM chunks")["n"],
            "pendientes": q("SELECT COUNT(*) n FROM document_versions WHERE extraction_status IN"
                            " ('pendiente_ocr','no_compatible','error','parcial')")["n"],
            "embeddings": q("SELECT COUNT(*) n FROM embeddings")["n"],
        }
