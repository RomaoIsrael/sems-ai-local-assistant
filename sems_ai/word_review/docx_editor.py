"""Edición de bajo nivel de DOCX conservando formato.

- Inserta párrafos nuevos después de un párrafo ancla copiando su formato de
  párrafo (sangrías, espaciado, alineación) y de carácter (fuente, tamaño).
- Resalta en amarillo el texto incorporado.
- Agrega comentarios reales de Word (comments.xml) anclados al texto incorporado.
- No toca tablas, imágenes, encabezados, pies ni numeraciones existentes.
"""
from __future__ import annotations

from copy import deepcopy

from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run


def body_paragraphs(document) -> list[Paragraph]:
    """Párrafos del cuerpo en orden (excluye los que están dentro de tablas)."""
    return list(document.paragraphs)


def is_heading(p: Paragraph) -> bool:
    name = (p.style.name if p.style is not None else "") or ""
    return name.lower().startswith(("heading", "título", "titulo", "title"))


def _template_rpr(p: Paragraph):
    for r in p.runs:
        if r.text.strip() and r._r.rPr is not None:
            return r._r.rPr
    return None


def insert_paragraph_after(anchor: Paragraph, text: str, highlight: bool = True) -> tuple[Paragraph, Run]:
    new_p = anchor._p.makeelement(qn("w:p"), {})
    ppr = anchor._p.pPr
    if ppr is not None:
        ppr_copy = deepcopy(ppr)
        if is_heading(anchor):
            for tag in ("w:pStyle", "w:numPr", "w:outlineLvl"):
                el = ppr_copy.find(qn(tag))
                if el is not None:
                    ppr_copy.remove(el)
        # no copiar marcas de cambio de sección del ancla
        sect = ppr_copy.find(qn("w:sectPr"))
        if sect is not None:
            ppr_copy.remove(sect)
        new_p.append(ppr_copy)
    anchor._p.addnext(new_p)
    para = Paragraph(new_p, anchor._parent)
    run = para.add_run(text)
    rpr = None if is_heading(anchor) else _template_rpr(anchor)
    if rpr is not None:
        run._r.insert(0, deepcopy(rpr))
    if highlight:
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return para, run


def append_to_paragraph(p: Paragraph, text: str, highlight: bool = True) -> Run:
    rpr = _template_rpr(p)
    run = p.add_run((" " if p.text and not p.text.endswith(" ") else "") + text)
    if rpr is not None:
        run._r.insert(0, deepcopy(rpr))
    if highlight:
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return run


def add_comment(document, runs, text: str, author: str, initials: str):
    return document.add_comment(runs=runs, text=text, author=author, initials=initials)
