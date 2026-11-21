"""Utilidades de prueba con LibreOffice (si está instalado) para recalcular fórmulas
y comprobar que otro procesador abre los archivos generados."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
needs_lo = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice no disponible en el entorno")


def convert(src: Path, fmt: str, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    profile = outdir / "lo_profile"
    cmd = [SOFFICE, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", fmt,
           "--outdir", str(outdir), str(src)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    out = outdir / (src.stem + "." + fmt.split(":")[0])
    assert out.exists(), f"LibreOffice no generó {out}"
    return out


def recalculated_values(xlsx: Path, tmp: Path):
    """Abre el libro en LibreOffice, recalcula y devuelve el libro con valores (data_only)."""
    import openpyxl

    out = convert(xlsx, "xlsx", tmp / "recalc")
    return openpyxl.load_workbook(out, data_only=True)
