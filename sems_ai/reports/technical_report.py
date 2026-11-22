"""Reportes técnicos editables en Word (.docx)."""
from __future__ import annotations

from pathlib import Path

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt

from sems_ai.audits.service import AuditService
from sems_ai.compliance.gap_analysis import RESULTS, GapAnalyzer
from sems_ai.database.db import Database, now_iso

DISCLAIMER = ("Este reporte contiene resultados preliminares generados por SEMS AI a partir de los documentos del "
              "repositorio local. La ausencia de texto en un documento no prueba incumplimiento operativo. Las "
              "conclusiones finales requieren validación del auditor o responsable designado.")


def _table(d, headers, rows, font_size=8):
    t = d.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for j, h in enumerate(headers):
        t.rows[0].cells[j].text = h
        for r in t.rows[0].cells[j].paragraphs[0].runs:
            r.font.bold = True
            r.font.size = Pt(font_size)
    for row in rows:
        cells = t.add_row().cells
        for j, v in enumerate(row):
            cells[j].text = "" if v is None else str(v)
            for p in cells[j].paragraphs:
                for r in p.runs:
                    r.font.size = Pt(font_size)
    return t


def _save(d, path: Path) -> Path:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"No se sobrescribe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))
    return path


def compliance_report(db: Database, analysis_id: int, path: Path, author: str = "") -> Path:
    ga = GapAnalyzer(db)
    a = db.query_one("SELECT * FROM compliance_analyses WHERE id=?", (analysis_id,))
    items = ga.items(analysis_id)
    summ = ga.summary(analysis_id)
    d = docx.Document()
    d.add_heading("Reporte técnico de análisis de cumplimiento documental", 0)
    for k, v in (("Análisis", a["title"]), ("Método", a["method"]), ("Fecha del análisis", a["created_at"]),
                 ("Fecha del reporte", now_iso()), ("Elaborado por", author or a["created_by"] or "")):
        p = d.add_paragraph()
        p.add_run(f"{k}: ").bold = True
        p.add_run(str(v or ""))
    w = d.add_paragraph(DISCLAIMER)
    for r in w.runs:
        r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    d.add_heading("1. Resumen de resultados preliminares", 1)
    _table(d, ["Resultado", "Cantidad"], [[k, summ[k]] for k in RESULTS] + [["Total", sum(summ.values())]], 10)
    pend = sum(1 for i in items if i["review_status"] == "Pendiente de revisión")
    d.add_paragraph(f"Ítems pendientes de revisión humana: {pend} de {len(items)}.")
    d.add_heading("2. Brechas identificadas", 1)
    gaps = [i for i in items if i["result"] in ("Parcialmente cubierto", "No identificado en el documento",
                                                "Requiere validación adicional")]
    if not gaps:
        d.add_paragraph("No se identificaron brechas documentales en el análisis preliminar.")
    for i in gaps:
        d.add_heading(f"{i['ident']} — numeral {i['numeral'] or 'no identificado'} ({i['result']})", 2)
        for k, v in (("Fuente", f"{i['source']}, pág. {i['req_page'] or '-'}"), ("Requisito", i["req_text"]),
                     ("Tipo de obligación", i["obligation_type"]), ("Sección local", i["local_section"]),
                     ("Evidencia encontrada", i["evidence"] or "Ninguna cita literal identificada"),
                     ("Brecha", i["gap"]), ("Recomendación", i["recommendation"]),
                     ("Justificación", i["justification"]), ("Confianza", i["confidence"]),
                     ("Revisión humana", f"{i['review_status']} {i['reviewer'] or ''}")):
            p = d.add_paragraph()
            p.add_run(f"{k}: ").bold = True
            p.add_run(str(v or "-"))
    d.add_heading("3. Matriz completa", 1)
    _table(d, ["ID", "Numeral", "Resultado", "Sección local", "Confianza", "Revisión"],
           [[i["ident"], i["numeral"], i["result"], i["local_section"], i["confidence"], i["review_status"]]
            for i in items])
    d.add_heading("4. Validación", 1)
    d.add_paragraph("Nombre del auditor / responsable: ______________________   Fecha: ____________   "
                    "Firma: ______________")
    return _save(d, path)


def audit_report(db: Database, audit_id: int, path: Path) -> Path:
    svc = AuditService(db)
    a = svc.audit(audit_id)
    m = svc.methodology(audit_id)
    d = docx.Document()
    d.add_heading(f"Informe de auditoría — {a['title']}", 0)
    for k in ("code", "standard", "sop", "asset", "scope", "start_date", "end_date", "lead_auditor", "auditors",
              "auditees"):
        p = d.add_paragraph()
        p.add_run(k.replace("_", " ").capitalize() + ": ").bold = True
        p.add_run(str(a[k] or ""))
    d.add_paragraph(f"Metodología: {m.name}. Fuente: {m.source or 'no documentada (provisional)'}.")
    d.add_heading("Resultados por respuesta", 1)
    _table(d, ["Respuesta", "Cantidad"], list(svc.counts(audit_id).items()), 10)
    d.add_heading("Hallazgos", 1)
    f = svc.findings(audit_id)
    if f:
        _table(d, ["Ref.", "Pregunta", "Tipo", "Descripción", "Responsable", "Estado"],
               [[x["ref"], x["qid"], x["finding_type"], x["description"], x["responsible"], x["status"]] for x in f])
    else:
        d.add_paragraph("No se registraron hallazgos.")
    d.add_heading("Acciones correctivas", 1)
    acts = svc.actions(audit_id)
    if acts:
        _table(d, ["Hallazgo", "Acción", "Responsable", "Fecha", "Estado", "Eficacia"],
               [[x["finding_ref"], x["action"], x["responsible"], x["due_date"], x["status"],
                 x["effectiveness_check"]] for x in acts])
    else:
        d.add_paragraph("No se registraron acciones correctivas.")
    d.add_heading("Conclusiones", 1)
    d.add_paragraph("[A completar por el auditor líder. SEMS AI no genera conclusiones de auditoría.]")
    return _save(d, path)
