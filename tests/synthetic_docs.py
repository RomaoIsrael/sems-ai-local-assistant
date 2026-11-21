"""Generador de documentos SINTÉTICOS para pruebas automatizadas.

IMPORTANTE: estos documentos son ficticios, creados solo para verificar el
software. Usan el prefijo de código "TEST-" y la marca "DOCUMENTO SINTÉTICO DE
PRUEBA". No representan estándares, procedimientos ni planes corporativos reales.
"""
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

MARK = "DOCUMENTO SINTÉTICO DE PRUEBA — NO CORRESPONDE A NINGÚN ESTÁNDAR REAL"

STANDARD_REQS = [
    ("1", "Generalidades", None),
    ("1.1", "Objeto", "Este estándar sintético establece requisitos de prueba para la gestión de desechos."),
    ("1.2", "Inventario de desechos",
     "El operador deberá mantener un inventario actualizado de todos los desechos generados, incluyendo "
     "cantidades mensuales, clasificación y punto de generación."),
    ("1.3", "Almacenamiento temporal",
     "Las áreas de almacenamiento temporal de desechos peligrosos deberán contar con cubierta, piso "
     "impermeabilizado, cubeto de contención y señalización."),
    ("1.4", "Gestores ambientales",
     "El operador deberá auditar anualmente a los gestores ambientales que reciben desechos, y conservar "
     "las evidencias de la auditoría durante cinco años."),
    ("1.5", "Capacitación",
     "Se recomienda que el personal reciba capacitación semestral en manejo de desechos."),
    ("1.6", "Manifiestos",
     "Cada transporte de desechos peligrosos deberá estar respaldado por un manifiesto único firmado por "
     "el generador, el transportista y el gestor."),
]

PLAN_SECTIONS = [
    ("1. Objetivo", "Este plan sintético describe la gestión de desechos en una instalación de prueba."),
    ("2. Inventario", "El supervisor ambiental mantiene un inventario actualizado de los desechos generados, "
                      "con cantidades mensuales, clasificación y punto de generación."),
    ("3. Almacenamiento", "Los desechos peligrosos se almacenan temporalmente en un área con cubierta y "
                          "señalización."),
    ("4. Transporte", "El transporte se realiza con transportistas calificados."),
]


def build_standard_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "TEST-STD-001 Rev. 0 — " + MARK
    d.add_heading("TEST-STD-001 Estándar sintético de gestión de desechos", 0)
    d.add_paragraph(MARK)
    for num, title, body in STANDARD_REQS:
        d.add_heading(f"{num} {title}", 1 if "." not in num else 2)
        if body:
            d.add_paragraph(body)
    d.save(path)
    return path


def build_standard_pdf(path: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    lines = ["TEST-STD-001 Estándar sintético de gestión de desechos", "Revisión: 0", MARK, ""]
    for num, title, body in STANDARD_REQS:
        lines.append(f"{num} {title}")
        if body:
            words, cur = body.split(), ""
            for w in words:
                if len(cur) + len(w) > 85:
                    lines.append(cur)
                    cur = ""
                cur += w + " "
            lines.append(cur.strip())
        lines.append("")
    for i, ln in enumerate(lines):
        if y > 780:
            page = doc.new_page()
            y = 60
        page.insert_text((50, y), ln, fontsize=10)
        y += 14
    doc.save(path)
    return path


def _png_bytes(w: int = 4, h: int = 4) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def build_plan_docx(path: Path) -> Path:
    import docx
    from docx.shared import Cm, Pt

    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(11)
    sec = d.sections[0]
    sec.header.paragraphs[0].text = "TEST-PLAN-001 Plan sintético de gestión de desechos — " + MARK
    sec.footer.paragraphs[0].text = "Pie de página de prueba — Rev. 0"
    d.add_heading("TEST-PLAN-001 Plan sintético de gestión de desechos", 0)
    for title, body in PLAN_SECTIONS:
        d.add_heading(title, 1)
        p = d.add_paragraph(body)
        p.paragraph_format.left_indent = Cm(1)
        p.paragraph_format.space_after = Pt(6)
    t = d.add_table(rows=3, cols=3)
    t.style = "Table Grid"
    for r, row in enumerate([("Código", "Desecho", "Clasificación"), ("D-01", "Aceite usado", "Peligroso"),
                             ("D-02", "Papel", "No peligroso")]):
        for c, val in enumerate(row):
            t.cell(r, c).text = val
    d.add_picture(io.BytesIO(_png_bytes()), width=Cm(1))
    d.save(path)
    return path


def build_xlsx(path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventario"
    ws.append(["Código", "Desecho", "Cantidad (kg)"])
    ws.append(["D-01", "Aceite usado", 120])
    ws.append(["D-02", "Papel", 35])
    ws["E1"] = MARK
    wb.save(path)
    return path


def build_all(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return {
        "standard_docx": build_standard_docx(folder / "TEST-STD-001 Estandar sintetico.docx"),
        "standard_pdf": build_standard_pdf(folder / "TEST-STD-001 Estandar sintetico.pdf"),
        "plan_docx": build_plan_docx(folder / "TEST-PLAN-001 Plan sintetico.docx"),
        "xlsx": build_xlsx(folder / "TEST-INV-001 Inventario sintetico.xlsx"),
    }
