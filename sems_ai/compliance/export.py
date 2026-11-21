"""Exportación de la matriz de brechas / cumplimiento a Excel."""
from __future__ import annotations

from pathlib import Path

from openpyxl.styles import Font

from sems_ai.compliance.gap_analysis import RESULTS, REVIEW_STATES, GapAnalyzer
from sems_ai.database.db import Database, now_iso
from sems_ai.excel.builder import RESULT_COLORS, WorkbookBuilder

HEADERS = ["ID", "Fuente", "Numeral", "Pág. fuente", "Texto del requisito", "Tipo de obligación",
           "Documento local", "Sección local", "Pág. local", "Evidencia encontrada (cita literal)",
           "Resultado preliminar", "Brecha identificada", "Recomendación", "Justificación", "Acción propuesta",
           "Nivel de confianza", "Estado de revisión humana", "Revisor", "Fecha revisión", "Notas del revisor"]


def export_gap_matrix(db: Database, analysis_id: int, path: Path) -> Path:
    ga = GapAnalyzer(db)
    a = db.query_one("SELECT * FROM compliance_analyses WHERE id=?", (analysis_id,))
    items = ga.items(analysis_id)
    wb = WorkbookBuilder()
    ws = wb.sheet("Matriz de brechas")
    rows = [[i["ident"], i["source"], i["numeral"], i["req_page"], i["req_text"], i["obligation_type"],
             i["local_document"], i["local_section"], i["local_page"], i["evidence"], i["result"], i["gap"],
             i["recommendation"], i["justification"], i["proposed_action"], i["confidence"], i["review_status"],
             i["reviewer"], i["reviewed_at"], i["reviewer_notes"]] for i in items]
    start = wb.title_block(ws, "Matriz de brechas documentales", [
        ("Análisis", a["title"]), ("Método", a["method"]), ("Fecha", a["created_at"]), ("Notas", a["notes"]),
        ("Advertencia", "Resultados preliminares. La ausencia de texto no prueba incumplimiento operativo. "
                        "Las conclusiones requieren validación del auditor o responsable designado.")]) + 1
    first, last = wb.table(ws, HEADERS, rows, start_row=start,
                           widths=[18, 18, 9, 7, 60, 13, 18, 25, 7, 50, 22, 40, 40, 45, 35, 11, 20, 14, 16, 30],
                           validations={11: RESULTS, 16: ["Baja", "Media", "Alta"], 17: REVIEW_STATES},
                           table_name="MatrizBrechas")
    wb.color_by_value(ws, f"K{first}:K{last}", RESULT_COLORS)
    # Resumen con fórmulas (se recalculan si el auditor cambia resultados)
    rs = wb.sheet("Resumen")
    wb.title_block(rs, "Resumen de resultados (fórmulas sobre la matriz)", [("Generado", now_iso())])
    for c, h in enumerate(("Resultado", "Cantidad", "% del total"), start=1):
        rs.cell(row=4, column=c, value=h).font = Font(bold=True)
    rng = f"'Matriz de brechas'!$K${first}:$K${last}"
    for k, res in enumerate(RESULTS, start=5):
        rs.cell(row=k, column=1, value=res)
        rs.cell(row=k, column=2, value=f"=COUNTIF({rng},A{k})")
        rs.cell(row=k, column=3, value=f"=IF($B$10=0,\"\",B{k}/$B$10)").number_format = "0.0%"
    rs.cell(row=10, column=1, value="Total requisitos evaluados").font = Font(bold=True)
    rs.cell(row=10, column=2, value="=SUM(B5:B9)")
    rs.cell(row=12, column=1, value="Pendientes de revisión humana")
    rs.cell(row=12, column=2, value=f"=COUNTIF('Matriz de brechas'!$Q${first}:$Q${last},\"Pendiente de revisión\")")
    rs.column_dimensions["A"].width = 40
    rs.column_dimensions["B"].width = 12
    rs.column_dimensions["C"].width = 12
    wb.bar_chart(rs, "Resultados preliminares", (1, 5, 9), (2, 4, 9), "E4")
    return wb.save(path)
