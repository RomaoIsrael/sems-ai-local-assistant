"""Exportación de una auditoría SEMS a Excel con 9 pestañas.

El Scorecard solo calcula métricas permitidas por la metodología: conteos por
opción de respuesta siempre; porcentaje de conformidad solo si la metodología lo
autoriza y cita su fuente. Los campos sin datos se dejan vacíos.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from sems_ai.audits.service import AuditService
from sems_ai.database.db import Database, now_iso
from sems_ai.excel.builder import WorkbookBuilder

Q_HEADERS = ["ID", "Fuente", "Numeral", "Pregunta original", "Traducción técnica", "Guía para el auditor",
             "Evidencia requerida", "Resultado", "Evidencia encontrada", "Observaciones", "Hallazgo", "Responsable",
             "Fecha de cierre", "Verificación de eficacia", "Origen de la pregunta"]
Q_WIDTHS = [11, 18, 9, 55, 35, 35, 30, 16, 40, 35, 12, 16, 12, 25, 40]


def _q_rows(qs):
    return [[q["qid"], q["source"], q["numeral"], q["question"], q["translation"], q["auditor_guide"],
             q["required_evidence"], q["result"], q["evidence_found"], q["observations"], q["finding"],
             q["responsible"], q["close_date"], q["effectiveness"], q["origin_reference"]] for q in qs]


def export_audit(db: Database, audit_id: int, path: Path) -> Path:
    svc = AuditService(db)
    a = svc.audit(audit_id)
    m = svc.methodology(audit_id)
    official = svc.questions(audit_id, "oficial")
    comp = svc.questions(audit_id, "complementaria")
    wb = WorkbookBuilder()

    # 1. Cover
    ws = wb.sheet("Cover")
    wb.title_block(ws, f"Auditoría SEMS — {a['title']}", [
        ("Código", a["code"]), ("Estándar", a["standard"]), ("SOP", a["sop"]), ("Activo", a["asset"]),
        ("Alcance", a["scope"]), ("Fecha inicio", a["start_date"]), ("Fecha fin", a["end_date"]),
        ("Auditor líder", a["lead_auditor"]), ("Equipo auditor", a["auditors"]), ("Auditados", a["auditees"]),
        ("Estado", a["status"]), ("Metodología", m.name),
        ("Fuente de la metodología", m.source or "NO DOCUMENTADA — configuración provisional"),
        ("Opciones de respuesta", " / ".join(m.response_options)), ("Notas de metodología", m.notes),
        ("Preguntas oficiales", len(official)), ("Preguntas complementarias", len(comp)),
        ("Generado", now_iso()),
        ("Aviso", "Las preguntas complementarias fueron propuestas a partir de requisitos y no forman parte del "
                  "checklist oficial.")])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 90

    # 2-3. Checklists
    ranges = {}
    for title, qs, tname in (("Checklist oficial", official, "ChecklistOficial"),
                             ("Revisión complementaria", comp, "RevisionComplementaria")):
        s = wb.sheet(title)
        first, last = wb.table(s, Q_HEADERS, _q_rows(qs), widths=Q_WIDTHS, validations={8: m.response_options},
                               table_name=tname, date_cols=())
        ranges[title] = (first, last)

    # 4. Evidencias
    s = wb.sheet("Evidencias")
    wb.table(s, ["N°", "Pregunta", "Descripción", "Documento", "Código", "Referencia", "SHA-256", "Fecha", "Registrado por"],
             [[i + 1, e["qid"], e["description"], e["doc_name"], e["doc_code"], e["reference"], e["sha256"],
               e["added_at"], e["added_by"]] for i, e in enumerate(svc.evidence(audit_id))],
             widths=[5, 11, 50, 35, 18, 25, 20, 18, 14], table_name="Evidencias", extra_blank_rows=5)

    # 5. Non-Compliance
    s = wb.sheet("Non-Compliance")
    fnd = svc.findings(audit_id)
    wb.table(s, ["Ref.", "Pregunta", "Tipo", "Descripción", "Requisito", "Evidencia", "Responsable", "Fecha compromiso",
                 "Estado"],
             [[f["ref"], f["qid"], f["finding_type"], f["description"], f["requirement"], f["evidence"],
               f["responsible"], f["due_date"], f["status"]] for f in fnd],
             widths=[8, 11, 18, 55, 40, 40, 16, 14, 12],
             validations={3: m.finding_types, 9: ["Abierto", "En proceso", "Cerrado"]}, table_name="NoConformidades",
             extra_blank_rows=5)

    # 6. Acciones correctivas
    s = wb.sheet("Acciones correctivas")
    acts = svc.actions(audit_id)
    wb.table(s, ["Hallazgo", "Causa raíz", "Acción", "Responsable", "Fecha compromiso", "Estado", "Fecha de cierre",
                 "Verificación de eficacia", "Fecha verificación"],
             [[x["finding_ref"], x["root_cause"], x["action"], x["responsible"], x["due_date"], x["status"],
               x["closed_date"], x["effectiveness_check"], x["effectiveness_date"]] for x in acts],
             widths=[10, 35, 50, 16, 14, 12, 14, 35, 14],
             validations={6: ["Abierta", "En proceso", "Cerrada", "Cerrada - eficaz", "Cerrada - no eficaz"]},
             table_name="AccionesCorrectivas", extra_blank_rows=5)

    # 7. Scorecard (fórmulas sobre las pestañas de checklist)
    s = wb.sheet("Scorecard")
    s["A1"] = "Scorecard"
    s["A1"].font = Font(bold=True, size=14)
    s["A2"] = ("Métricas según metodología: " + m.name + (f" — Fuente: {m.source}" if m.source else
                                                          " — PROVISIONAL: solo conteos, sin porcentajes."))
    hdr = ["Respuesta", "Checklist oficial", "Revisión complementaria", "Total"]
    for j, h in enumerate(hdr, start=1):
        s.cell(row=4, column=j, value=h).font = Font(bold=True)
    fo, lo = ranges["Checklist oficial"]
    fc, lc = ranges["Revisión complementaria"]
    r = 5
    for opt in m.response_options:
        s.cell(row=r, column=1, value=opt)
        s.cell(row=r, column=2, value=f"=COUNTIF('Checklist oficial'!$H${fo}:$H${lo},$A{r})")
        s.cell(row=r, column=3, value=f"=COUNTIF('Revisión complementaria'!$H${fc}:$H${lc},$A{r})")
        s.cell(row=r, column=4, value=f"=B{r}+C{r}")
        r += 1
    s.cell(row=r, column=1, value="Sin respuesta")
    s.cell(row=r, column=2, value=f"=COUNTA('Checklist oficial'!$A${fo}:$A${lo})-COUNTA('Checklist oficial'!$H${fo}:$H${lo})")
    s.cell(row=r, column=3, value=f"=COUNTA('Revisión complementaria'!$A${fc}:$A${lc})-"
                                  f"COUNTA('Revisión complementaria'!$H${fc}:$H${lc})")
    s.cell(row=r, column=4, value=f"=B{r}+C{r}")
    last_opt = r
    r += 1
    s.cell(row=r, column=1, value="Total preguntas").font = Font(bold=True)
    for col in (2, 3, 4):
        L = get_column_letter(col)
        s.cell(row=r, column=col, value=f"=SUM({L}5:{L}{last_opt})")
    total_row = r
    r += 2
    if m.allow_percentage:
        def sum_of(values, col):
            return "+".join(f"SUMIF($A$5:$A${last_opt},\"{v}\",{col}$5:{col}${last_opt})" for v in values)

        s.cell(row=r, column=1, value="% conformidad (conformes / (conformes + no conformes))").font = Font(bold=True)
        for col in ("B", "C", "D"):
            num = sum_of(m.compliant_values, col)
            den = f"{num}+{sum_of(m.noncompliant_values, col)}"
            c = s[f"{col}{r}"]
            c.value = f"=IF(({den})=0,\"\",({num})/({den}))"
            c.number_format = "0.0%"
        s.cell(row=r + 1, column=1, value=f"Fórmula autorizada por: {m.source}")
    else:
        s.cell(row=r, column=1, value="Porcentaje de cumplimiento: no calculado (la metodología configurada no "
                                      "define criterios de ponderación ni aprobación).")
    s.column_dimensions["A"].width = 55
    for L in "BCD":
        s.column_dimensions[L].width = 18
    wb.bar_chart(s, "Respuestas (total)", (1, 5, last_opt), (4, 4, last_opt), "F4")
    _ = total_row

    # 8. Matriz de trazabilidad
    s = wb.sheet("Matriz de trazabilidad")
    ev_by_q: dict = {}
    for e in svc.evidence(audit_id):
        ev_by_q.setdefault(e["question_id"], []).append(e["reference"] or e["doc_code"] or e["description"][:30])
    f_by_q: dict = {}
    for f in fnd:
        f_by_q.setdefault(f["question_id"], []).append(f["ref"])
    a_by_f: dict = {}
    for x in acts:
        a_by_f.setdefault(x["finding_ref"], []).append(f"AC-{x['id']}")
    rows = []
    for q in official + comp:
        frefs = f_by_q.get(q["id"], [])
        rows.append([q["qid"], q["origin"], q["source"], q["numeral"], q["result"],
                     "; ".join(ev_by_q.get(q["id"], [])), "; ".join(frefs),
                     "; ".join(sum((a_by_f.get(fr, []) for fr in frefs), [])), q["origin_reference"]])
    wb.table(s, ["Pregunta", "Origen", "Fuente", "Numeral", "Resultado", "Evidencias", "Hallazgos",
                 "Acciones correctivas", "Referencia de origen"], rows,
             widths=[11, 14, 18, 9, 16, 35, 15, 20, 50], table_name="Trazabilidad")

    # 9. Informe ejecutivo
    s = wb.sheet("Informe ejecutivo")
    wb.title_block(s, "Informe ejecutivo", [
        ("Auditoría", a["title"]), ("Activo", a["asset"]), ("Alcance", a["scope"]),
        ("Período", f"{a['start_date'] or ''} — {a['end_date'] or ''}"), ("Auditor líder", a["lead_auditor"])])
    s["A8"] = "Total de preguntas"
    s["B8"] = f"=Scorecard!D{total_row}"
    s["A9"] = "Hallazgos registrados"
    s["B9"] = f"=COUNTA('Non-Compliance'!A2:A{len(fnd) + 6})"
    s["A10"] = "Acciones correctivas abiertas"
    s["B10"] = f"=COUNTIF('Acciones correctivas'!F2:F{len(acts) + 6},\"Abierta\")+" \
               f"COUNTIF('Acciones correctivas'!F2:F{len(acts) + 6},\"En proceso\")"
    s["A12"] = "Conclusiones del auditor"
    s["A12"].font = Font(bold=True)
    s["A13"] = "[A completar por el auditor líder. No se generan conclusiones automáticas.]"
    s["A15"] = "Fortalezas"
    s["A15"].font = Font(bold=True)
    s["A16"] = "[A completar por el auditor]"
    s["A18"] = "Firma / aprobación"
    s["A18"].font = Font(bold=True)
    s.column_dimensions["A"].width = 40
    s.column_dimensions["B"].width = 60
    return wb.save(path)
