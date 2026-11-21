"""Utilidades para generar libros Excel editables y funcionales con openpyxl.

Incluye: bloques de título, tablas con filtros, listas desplegables (validación
de datos basada en una hoja oculta "Listas"), formato condicional, fórmulas y
gráficos. Los campos sin datos se dejan vacíos: nunca se rellenan con valores
inventados.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
LABEL_FONT = Font(bold=True)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

RESULT_COLORS = {
    "Cubierto documentalmente": "C6EFCE",
    "Parcialmente cubierto": "FFEB9C",
    "No identificado en el documento": "FFC7CE",
    "Requiere validación adicional": "DDEBF7",
    "No aplicable, pendiente de justificar": "EDEDED",
}


class WorkbookBuilder:
    def __init__(self):
        self.wb = Workbook()
        self._first = True
        self._lists = None
        self._list_cache: dict[tuple, str] = {}

    def sheet(self, title: str):
        title = title[:31]
        if self._first:
            ws = self.wb.active
            ws.title = title
            self._first = False
        else:
            ws = self.wb.create_sheet(title)
        return ws

    # --------------------------------------------------------------- bloques
    def title_block(self, ws, title: str, pairs: Sequence[tuple[str, object]] = (), row: int = 1) -> int:
        ws.cell(row=row, column=1, value=title).font = TITLE_FONT
        r = row + 1
        for k, v in pairs:
            ws.cell(row=r, column=1, value=k).font = LABEL_FONT
            c = ws.cell(row=r, column=2, value=v if v not in (None, "") else None)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            r += 1
        return r

    def list_range(self, values: Sequence[str]) -> str:
        """Escribe una lista en la hoja oculta 'Listas' y devuelve un nombre definido."""
        key = tuple(values)
        if key in self._list_cache:
            return self._list_cache[key]
        if self._lists is None:
            self._lists = self.wb.create_sheet("Listas")
            self._lists.sheet_state = "hidden"
        col = len(self._list_cache) + 1
        for i, v in enumerate(values, start=1):
            self._lists.cell(row=i, column=col, value=v)
        letter = get_column_letter(col)
        name = f"Lista_{col}"
        ref = f"{quote_sheetname('Listas')}!${letter}$1:${letter}${len(values)}"
        self.wb.defined_names[name] = DefinedName(name, attr_text=ref)
        self._list_cache[key] = name
        return name

    def add_list_validation(self, ws, cell_range: str, values: Sequence[str], allow_blank: bool = True,
                            prompt: str | None = None) -> DataValidation:
        name = self.list_range(values)
        dv = DataValidation(type="list", formula1=f"={name}", allow_blank=allow_blank, showDropDown=False)
        dv.error = "Seleccione un valor de la lista."
        dv.errorTitle = "Valor no válido"
        dv.showErrorMessage = True
        if prompt:
            dv.prompt = prompt
            dv.showInputMessage = True
        ws.add_data_validation(dv)
        dv.add(cell_range)
        return dv

    def table(self, ws, headers: Sequence[str], rows: Iterable[Sequence[object]], start_row: int = 1,
              widths: Sequence[int] | None = None, validations: dict[int, Sequence[str]] | None = None,
              table_name: str | None = None, extra_blank_rows: int = 0, wrap: bool = True,
              date_cols: Sequence[int] = ()) -> tuple[int, int]:
        """Escribe una tabla. Devuelve (fila_primera_dato, fila_última)."""
        for j, h in enumerate(headers, start=1):
            c = ws.cell(row=start_row, column=j, value=h)
            c.fill, c.font, c.border = HEADER_FILL, HEADER_FONT, BORDER
            c.alignment = Alignment(wrap_text=True, vertical="center")
        r = start_row
        for r_off, row in enumerate(rows, start=1):
            r = start_row + r_off
            for j, v in enumerate(row, start=1):
                c = ws.cell(row=r, column=j, value=(v if v not in ("",) else None))
                c.border = BORDER
                if wrap:
                    c.alignment = WRAP
        last = max(r, start_row + 1) + extra_blank_rows
        for rr in range(r + 1, last + 1):
            for j in range(1, len(headers) + 1):
                ws.cell(row=rr, column=j).border = BORDER
        if widths:
            for j, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(j)].width = w
        ref = f"A{start_row}:{get_column_letter(len(headers))}{last}"
        if table_name:
            t = Table(displayName=table_name.replace(" ", "_"), ref=ref)
            t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
            ws.add_table(t)
        else:
            ws.auto_filter.ref = ref
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
        for col, values in (validations or {}).items():
            L = get_column_letter(col)
            self.add_list_validation(ws, f"{L}{start_row + 1}:{L}{max(last, start_row + 200)}", values)
        for col in date_cols:
            L = get_column_letter(col)
            dv = DataValidation(type="date", operator="greaterThan", formula1="DATE(1990,1,1)", allow_blank=True)
            dv.error = "Ingrese una fecha válida (dd/mm/aaaa)."
            dv.showErrorMessage = True
            ws.add_data_validation(dv)
            dv.add(f"{L}{start_row + 1}:{L}{max(last, start_row + 200)}")
            for rr in range(start_row + 1, max(last, start_row + 200) + 1):
                ws[f"{L}{rr}"].number_format = "DD/MM/YYYY"
        return start_row + 1, last

    def color_by_value(self, ws, cell_range: str, mapping: dict[str, str]) -> None:
        for value, color in mapping.items():
            ws.conditional_formatting.add(
                cell_range, CellIsRule(operator="equal", formula=[f'"{value}"'],
                                       fill=PatternFill("solid", fgColor=color, bgColor=color)))

    def highlight_formula(self, ws, cell_range: str, formula: str, color: str) -> None:
        ws.conditional_formatting.add(cell_range, FormulaRule(formula=[formula],
                                                              fill=PatternFill("solid", fgColor=color,
                                                                               bgColor=color)))

    def bar_chart(self, ws, title: str, cats_ref: tuple, data_ref: tuple, anchor: str) -> None:
        """cats_ref/data_ref: (min_col, min_row, max_row) en la hoja ws."""
        ch = BarChart()
        ch.type = "bar"
        ch.title = title
        ch.legend = None
        data = Reference(ws, min_col=data_ref[0], min_row=data_ref[1], max_row=data_ref[2])
        cats = Reference(ws, min_col=cats_ref[0], min_row=cats_ref[1], max_row=cats_ref[2])
        ch.add_data(data, titles_from_data=True)
        ch.set_categories(cats)
        ch.height, ch.width = 7, 16
        ws.add_chart(ch, anchor)

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"No se sobrescribe un archivo existente: {path}")
        self.wb.save(str(path))
        return path


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    from datetime import datetime

    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = folder / f"{stem}_{stamp}{ext}"
    k = 1
    while p.exists():
        p = folder / f"{stem}_{stamp}_{k}{ext}"
        k += 1
    return p
