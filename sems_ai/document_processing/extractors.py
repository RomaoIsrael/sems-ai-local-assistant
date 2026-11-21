"""Extracción de texto por formato.

Cada extractor devuelve un ``ExtractionResult`` con segmentos (``Segment``) que
conservan la ubicación original (página, hoja/celda, diapositiva, párrafo) para
permitir citas trazables. Si un formato no se puede procesar, el resultado se
marca como ``no_compatible`` o ``pendiente_ocr`` — nunca se inventa contenido.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

STATUS_OK = "ok"
STATUS_PARTIAL = "parcial"
STATUS_UNSUPPORTED = "no_compatible"
STATUS_PENDING_OCR = "pendiente_ocr"
STATUS_ERROR = "error"
STATUS_CONTAINER = "contenedor"


@dataclass
class Segment:
    text: str
    page: int | None = None
    section: str | None = None
    location: str | None = None  # p.ej. "Hoja1!A1:D20", "Diapositiva 3", "Párrafo 12"


@dataclass
class ExtractionResult:
    status: str
    segments: list[Segment] = field(default_factory=list)
    message: str = ""
    page_count: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)


HEADING_RE = re.compile(r"^\s*((?:\d+\.)*\d+)\.?\s+([A-ZÁÉÍÓÚÑ][^\n]{2,120})$")


def _detect_section(line: str) -> str | None:
    m = HEADING_RE.match(line)
    if m and len(line) < 140:
        return f"{m.group(1)} {m.group(2).strip()}"
    return None


# ---------------------------------------------------------------- PDF
def extract_pdf(path: Path, ocr: "OcrEngine | None" = None) -> ExtractionResult:
    try:
        import pymupdf  # PyMuPDF
    except ImportError:  # pragma: no cover
        return ExtractionResult(STATUS_UNSUPPORTED, message="PyMuPDF no instalado.")
    segs: list[Segment] = []
    pending_pages: list[int] = []
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        return ExtractionResult(STATUS_ERROR, message=f"No se pudo abrir el PDF: {exc}")
    with doc:
        if doc.needs_pass:
            return ExtractionResult(STATUS_UNSUPPORTED, message="PDF protegido con contraseña.")
        current_section = None
        for pno, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            if not text.strip():
                if ocr and ocr.available:
                    try:
                        pix = page.get_pixmap(dpi=300)
                        text = ocr.image_bytes_to_text(pix.tobytes("png"))
                    except Exception:
                        text = ""
                if not text.strip():
                    if page.get_images():
                        pending_pages.append(pno)
                    continue
            for line in text.splitlines():
                sec = _detect_section(line)
                if sec:
                    current_section = sec
            segs.append(Segment(text=text, page=pno, section=current_section, location=f"Página {pno}"))
        count = doc.page_count
    if not segs and pending_pages:
        return ExtractionResult(STATUS_PENDING_OCR, [], "PDF escaneado: requiere OCR (Tesseract no disponible).", count)
    if pending_pages:
        return ExtractionResult(STATUS_PARTIAL, segs,
                                f"Páginas sin texto pendientes de OCR: {pending_pages}", count)
    if not segs:
        return ExtractionResult(STATUS_PARTIAL, [], "El PDF no contiene texto extraíble.", count)
    return ExtractionResult(STATUS_OK, segs, "", count)


# ---------------------------------------------------------------- DOCX
def iter_docx_blocks(document):
    """Itera párrafos y tablas en el orden del cuerpo del documento."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _heading_level(paragraph) -> int | None:
    name = (paragraph.style.name if paragraph.style is not None else "") or ""
    m = re.match(r"(?:Heading|Título|Titulo)\s*(\d)", name, re.I)
    if m:
        return int(m.group(1))
    if name.lower() in ("title", "título", "titulo"):
        return 0
    return None


def extract_docx(path: Path) -> ExtractionResult:
    try:
        import docx
    except ImportError:  # pragma: no cover
        return ExtractionResult(STATUS_UNSUPPORTED, message="python-docx no instalado.")
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        return ExtractionResult(STATUS_ERROR, message=f"No se pudo abrir el DOCX: {exc}")
    from docx.table import Table

    segs: list[Segment] = []
    section = None
    pidx = -1
    buf: list[str] = []
    buf_start = 0

    def flush():
        nonlocal buf
        if buf:
            segs.append(Segment("\n".join(buf), None, section, f"Párrafos {buf_start}-{pidx}"))
            buf = []

    for block in iter_docx_blocks(document):
        if isinstance(block, Table):
            rows = []
            for r in block.rows:
                cells = []
                for c in r.cells:
                    t = c.text.strip()
                    if not cells or cells[-1] != t:
                        cells.append(t)
                rows.append(" | ".join(cells))
            txt = "\n".join(rows).strip()
            if txt:
                flush()
                segs.append(Segment(txt, None, section, f"Tabla tras párrafo {pidx}"))
            continue
        pidx += 1
        text = block.text.strip()
        if not text:
            continue
        lvl = _heading_level(block)
        sec = _detect_section(text) if lvl is None else text
        if lvl is not None or (sec and len(text) < 100):
            flush()
            section = text
            buf_start = pidx
        if not buf:
            buf_start = pidx
        buf.append(text)
    flush()
    # encabezados / pies
    hf = []
    for s in document.sections:
        for part in (s.header, s.footer):
            t = "\n".join(p.text for p in part.paragraphs if p.text.strip())
            if t and t not in hf:
                hf.append(t)
    if hf:
        segs.append(Segment("\n".join(hf), None, "Encabezado/Pie de página", "Encabezados y pies"))
    if not segs:
        return ExtractionResult(STATUS_PARTIAL, [], "Documento Word sin texto.")
    return ExtractionResult(STATUS_OK, segs)


# ---------------------------------------------------------------- XLSX
def extract_xlsx(path: Path) -> ExtractionResult:
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
    except ImportError:  # pragma: no cover
        return ExtractionResult(STATUS_UNSUPPORTED, message="openpyxl no instalado.")
    try:
        # read_only + data_only: lee valores calculados; las macros NUNCA se ejecutan.
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:
        return ExtractionResult(STATUS_ERROR, message=f"No se pudo abrir el Excel: {exc}")
    segs: list[Segment] = []
    try:
        for ws in wb.worksheets:
            rows_txt: list[str] = []
            first_row = None
            last_row = 0
            for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if not vals:
                    continue
                if first_row is None:
                    first_row = r_idx
                last_row = r_idx
                rows_txt.append(f"[F{r_idx}] " + " | ".join(vals))
                if len(rows_txt) >= 40:
                    segs.append(Segment("\n".join(rows_txt), None, ws.title,
                                        f"{ws.title}!filas {first_row}-{last_row}"))
                    rows_txt, first_row = [], None
            if rows_txt:
                segs.append(Segment("\n".join(rows_txt), None, ws.title, f"{ws.title}!filas {first_row}-{last_row}"))
    finally:
        wb.close()
    _ = get_column_letter
    if not segs:
        return ExtractionResult(STATUS_PARTIAL, [], "Libro Excel sin contenido.")
    return ExtractionResult(STATUS_OK, segs)


# ---------------------------------------------------------------- PPTX
def extract_pptx(path: Path) -> ExtractionResult:
    try:
        from pptx import Presentation
    except ImportError:  # pragma: no cover
        return ExtractionResult(STATUS_UNSUPPORTED, message="python-pptx no instalado.")
    try:
        prs = Presentation(str(path))
    except Exception as exc:
        return ExtractionResult(STATUS_ERROR, message=f"No se pudo abrir la presentación: {exc}")
    segs = []
    for i, slide in enumerate(prs.slides, start=1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("Notas: " + slide.notes_slide.notes_text_frame.text.strip())
        if parts:
            segs.append(Segment("\n".join(parts), i, f"Diapositiva {i}", f"Diapositiva {i}"))
    if not segs:
        return ExtractionResult(STATUS_PARTIAL, [], "Presentación sin texto.", len(prs.slides))
    return ExtractionResult(STATUS_OK, segs, "", len(prs.slides))


# ---------------------------------------------------------------- texto plano
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_lines(text: str, per: int = 60, label: str = "Líneas") -> list[Segment]:
    lines = text.splitlines()
    segs = []
    section = None
    for start in range(0, len(lines), per):
        block = lines[start:start + per]
        for ln in block:
            s = _detect_section(ln)
            if s:
                section = s
        t = "\n".join(block).strip()
        if t:
            segs.append(Segment(t, None, section, f"{label} {start + 1}-{start + len(block)}"))
    return segs


def extract_txt(path: Path) -> ExtractionResult:
    segs = _split_lines(_read_text(path))
    return ExtractionResult(STATUS_OK if segs else STATUS_PARTIAL, segs)


def extract_csv(path: Path) -> ExtractionResult:
    text = _read_text(path)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [" | ".join(c.strip() for c in r if c.strip()) for r in csv.reader(io.StringIO(text), dialect)]
    segs = _split_lines("\n".join(r for r in rows if r), 40, "Filas")
    return ExtractionResult(STATUS_OK if segs else STATUS_PARTIAL, segs)


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def extract_html(path: Path) -> ExtractionResult:
    p = _HTMLText()
    p.feed(_read_text(path))
    text = re.sub(r"\n\s*\n+", "\n", "".join(p.parts))
    segs = _split_lines(text)
    return ExtractionResult(STATUS_OK if segs else STATUS_PARTIAL, segs)


def extract_xml(path: Path) -> ExtractionResult:
    # Sin resolución de entidades externas (XXE): se usa un parser de texto simple.
    text = re.sub(r"<!DOCTYPE[^>]*>", "", _read_text(path), flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    segs = _split_lines(text)
    return ExtractionResult(STATUS_OK if segs else STATUS_PARTIAL, segs)


def extract_json(path: Path) -> ExtractionResult:
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        return ExtractionResult(STATUS_ERROR, message=f"JSON no válido: {exc}")
    segs = _split_lines(json.dumps(data, indent=1, ensure_ascii=False))
    return ExtractionResult(STATUS_OK if segs else STATUS_PARTIAL, segs)


# ---------------------------------------------------------------- imágenes / OCR
class OcrEngine:
    """OCR local con Tesseract (opcional). Si no está instalado, ``available`` es False."""

    def __init__(self, tesseract_cmd: str = "", lang: str = "spa+eng"):
        self.lang = lang
        self.available = False
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return
        import pytesseract

        cmd = tesseract_cmd or shutil.which("tesseract")
        if not cmd:
            win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            cmd = str(win) if win.exists() else ""
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
            self.available = True

    def image_bytes_to_text(self, data: bytes) -> str:
        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return pytesseract.image_to_string(img, lang=self.lang)


def extract_image(path: Path, ocr: OcrEngine | None = None) -> ExtractionResult:
    if ocr and ocr.available:
        try:
            text = ocr.image_bytes_to_text(path.read_bytes())
        except Exception as exc:
            return ExtractionResult(STATUS_ERROR, message=f"Error de OCR: {exc}")
        if text.strip():
            return ExtractionResult(STATUS_OK, [Segment(text, 1, None, "Imagen (OCR)")],
                                    "Texto obtenido por OCR: verificar contra el original.", 1)
    return ExtractionResult(STATUS_PENDING_OCR, [], "Imagen sin texto extraído: pendiente de OCR.", 1)


EXTRACTORS = {
    ".pdf": "pdf", ".docx": "docx", ".docm": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx",
    ".pptx": "pptx", ".txt": "txt", ".md": "txt", ".csv": "csv", ".html": "html", ".htm": "html",
    ".xml": "xml", ".json": "json", ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".tif": "image", ".tiff": "image", ".zip": "zip",
}

SUPPORTED_EXTENSIONS = sorted(EXTRACTORS)


def extract(path: Path, ocr: OcrEngine | None = None) -> ExtractionResult:
    ext = path.suffix.lower()
    kind = EXTRACTORS.get(ext)
    if kind is None:
        return ExtractionResult(STATUS_UNSUPPORTED, message=f"Formato {ext or '(sin extensión)'} no compatible.")
    if kind == "zip":
        return ExtractionResult(STATUS_CONTAINER, message="Archivo ZIP: su contenido se importa por separado.")
    try:
        if kind == "pdf":
            return extract_pdf(path, ocr)
        if kind == "image":
            return extract_image(path, ocr)
        return globals()[f"extract_{kind}"](path)
    except Exception as exc:  # cualquier error se comunica, no se oculta
        return ExtractionResult(STATUS_ERROR, message=f"Error de extracción: {type(exc).__name__}: {exc}")
