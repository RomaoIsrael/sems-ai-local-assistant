"""Controles de seguridad sobre archivos entrantes.

- Verifica tamaño máximo.
- Contrasta extensión con firma binaria ("magic bytes").
- Detecta macros VBA en documentos Office (no se ejecutan nunca: solo se informa).
- Detecta JavaScript / acciones de lanzamiento en PDF.
- Extracción segura de ZIP: evita "zip slip", bombas de compresión y anidamiento excesivo.
"""
from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

OFFICE_ZIP_EXT = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm", ".dotx", ".xltx"}

MAGIC = {
    ".pdf": [b"%PDF-"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".tif": [b"II*\x00", b"MM\x00*"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
    ".zip": [b"PK\x03\x04", b"PK\x05\x06"],
}
for _ext in OFFICE_ZIP_EXT:
    MAGIC[_ext] = [b"PK\x03\x04"]


class UnsafeFileError(Exception):
    pass


@dataclass
class SafetyReport:
    flags: list[str] = field(default_factory=list)

    def add(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)


def sha256_file(path: Path, bufsize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(bufsize)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def inspect_file(path: Path, max_size_mb: int = 300) -> SafetyReport:
    """Inspección previa a la importación. Lanza UnsafeFileError si debe rechazarse."""
    rep = SafetyReport()
    size = path.stat().st_size
    if size > max_size_mb * 1024 * 1024:
        raise UnsafeFileError(f"El archivo supera el tamaño máximo permitido ({max_size_mb} MB).")
    if size == 0:
        rep.add("archivo_vacio")
        return rep
    ext = path.suffix.lower()
    with open(path, "rb") as fh:
        head = fh.read(16)
    sigs = MAGIC.get(ext)
    if sigs and not any(head.startswith(s) for s in sigs):
        raise UnsafeFileError(
            f"La firma binaria no coincide con la extensión {ext}. Posible archivo renombrado o dañado."
        )
    if head.startswith(b"MZ"):
        raise UnsafeFileError("El archivo es un ejecutable de Windows y no se admite.")
    if ext in OFFICE_ZIP_EXT:
        try:
            with zipfile.ZipFile(path) as zf:
                names = [n.lower() for n in zf.namelist()]
        except zipfile.BadZipFile as exc:
            raise UnsafeFileError(f"Documento Office dañado o no válido: {exc}") from exc
        if any(n.endswith("vbaproject.bin") for n in names):
            rep.add("contiene_macros_vba(no_ejecutadas)")
        if any("activex" in n for n in names):
            rep.add("contiene_activex(no_ejecutado)")
        if any(n.startswith("word/embeddings/") or n.startswith("xl/embeddings/") or
               n.startswith("ppt/embeddings/") for n in names):
            rep.add("contiene_objetos_incrustados")
    if ext == ".pdf":
        with open(path, "rb") as fh:
            data = fh.read(min(size, 50 * 1024 * 1024))
        for token, flag in ((b"/JavaScript", "pdf_javascript"), (b"/JS", "pdf_javascript"),
                            (b"/Launch", "pdf_accion_launch"), (b"/EmbeddedFile", "pdf_archivos_incrustados"),
                            (b"/OpenAction", "pdf_openaction")):
            if token in data:
                rep.add(flag)
    return rep


def safe_extract_zip(zip_path: Path, dest: Path, max_total_mb: int = 1024, max_ratio: int = 100,
                     max_files: int = 5000) -> list[Path]:
    """Extrae un ZIP de forma segura y devuelve la lista de archivos extraídos."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnsafeFileError(f"ZIP dañado: {exc}") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_files:
            raise UnsafeFileError(f"El ZIP contiene demasiados archivos ({len(infos)}).")
        total = sum(i.file_size for i in infos)
        if total > max_total_mb * 1024 * 1024:
            raise UnsafeFileError("El contenido descomprimido del ZIP supera el límite permitido.")
        compressed = sum(max(i.compress_size, 1) for i in infos) or 1
        if total / compressed > max_ratio:
            raise UnsafeFileError("Relación de compresión anómala: posible bomba ZIP.")
        for info in infos:
            if info.flag_bits & 0x1:
                raise UnsafeFileError("El ZIP está cifrado; descomprímalo manualmente tras verificarlo.")
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or (name.parts and ":" in name.parts[0]):
                raise UnsafeFileError(f"Ruta insegura dentro del ZIP: {info.filename}")
            target = (dest / Path(*name.parts)).resolve()
            if not str(target).startswith(str(dest)):
                raise UnsafeFileError(f"Ruta insegura dentro del ZIP: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                written = 0
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > info.file_size + 1024:
                        raise UnsafeFileError("Tamaño real distinto del declarado en el ZIP.")
                    dst.write(block)
            out.append(target)
    return out
