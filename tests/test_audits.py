import openpyxl
import pytest

from lo_utils import needs_lo, recalculated_values
from sems_ai.audits.excel_export import export_audit
from sems_ai.audits.service import AuditError, AuditService, Methodology
from sems_ai.database.db import Database

SHEETS = ["Cover", "Checklist oficial", "Revisión complementaria", "Evidencias", "Non-Compliance",
          "Acciones correctivas", "Scorecard", "Matriz de trazabilidad", "Informe ejecutivo"]


@pytest.fixture()
def checklist(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Numeral", "Pregunta", "Guía"])
    ws.append(["Q1", "1.2", "¿Existe inventario de desechos actualizado? (PRUEBA SINTÉTICA)", "Revisar registro"])
    ws.append(["Q2", "1.4", "¿Se auditó a los gestores? (PRUEBA SINTÉTICA)", ""])
    ws.append([None, None, None, None])
    ws.append(["Q3", "1.6", "¿Existen manifiestos firmados? (PRUEBA SINTÉTICA)", ""])
    p = tmp_path / "checklist_sintetico.xlsx"
    wb.save(p)
    return p


@pytest.fixture()
def audit(ctx, loaded, checklist):
    svc = AuditService(ctx.db, "tester")
    aid = svc.create_audit("Auditoría de prueba", asset="Activo de prueba", scope="Gestión de desechos")
    n = svc.import_official_checklist(aid, checklist, {"qid": "A", "numeral": "B", "question": "C",
                                                       "auditor_guide": "D"}, checklist_reference="Checklist TEST")
    assert n == 3
    svc.generate_complementary(aid, loaded["std"].version_id, exclude_numerals={"1.2", "1.4", "1.6"})
    return svc, aid


def test_official_vs_complementary(audit):
    svc, aid = audit
    off, comp = svc.questions(aid, "oficial"), svc.questions(aid, "complementaria")
    assert [q["qid"] for q in off] == ["Q1", "Q2", "Q3"]
    assert off[0]["question"].startswith("¿Existe inventario")  # literal
    assert "Checklist TEST" in off[0]["origin_reference"]
    assert len(comp) == 2 and all("NO es pregunta oficial" in q["origin_reference"] for q in comp)
    with pytest.raises(AuditError):
        svc.add_official_question(aid, "Q9", "¿Pregunta sin fuente?", checklist_reference="")


def test_methodology_rules(ctx, audit):
    svc, aid = audit
    q = svc.questions(aid)[0]
    with pytest.raises(AuditError):
        svc.record(q["id"], result="Cumple al 80%")  # no definida
    with pytest.raises(AuditError):
        Methodology(allow_percentage=True, compliant_values=["Conforme"], noncompliant_values=["No conforme"]).validate()
    with pytest.raises(AuditError):
        svc.add_finding(aid, "desc", "Mayor")  # tipo no definido


def test_results_persist(ctx, audit):
    svc, aid = audit
    q = svc.questions(aid)[0]
    svc.record(q["id"], result="Conforme", evidence_found="Registro REG-01")
    db2 = Database(ctx.settings.db_path)  # nueva conexión, como al reiniciar la app
    q2 = AuditService(db2).questions(aid)[0]
    assert q2["result"] == "Conforme" and q2["evidence_found"] == "Registro REG-01"


def _fill(svc, aid, ctx, loaded):
    qs = svc.questions(aid)
    svc.record(qs[0]["id"], result="Conforme")
    svc.record(qs[1]["id"], result="No conforme")
    svc.record(qs[2]["id"], result="No conforme")
    svc.record(qs[3]["id"], result="No aplica")
    svc.add_evidence(aid, "Inventario revisado", qs[0]["id"], document_id=loaded["xlsx"].document_id,
                     reference="TEST-INV-001")
    f = svc.add_finding(aid, "No se evidenció auditoría a gestores", "No conformidad", qs[1]["id"])
    svc.add_action(f, "Programar auditoría a gestores", "Responsable X", "2027-01-31")


@needs_lo
def test_audit_excel_provisional(ctx, loaded, audit, tmp_path):
    svc, aid = audit
    _fill(svc, aid, ctx, loaded)
    p = export_audit(ctx.db, aid, tmp_path / "auditoria.xlsx")
    wb = openpyxl.load_workbook(p)
    assert [s for s in wb.sheetnames if s != "Listas"] == SHEETS
    assert wb["Checklist oficial"].data_validations.dataValidation
    sc = wb["Scorecard"]
    text = " ".join(str(c.value) for row in sc.iter_rows() for c in row if c.value)
    assert "no calculado" in text
    assert not any("%" in c.number_format for row in sc.iter_rows() for c in row)
    v = recalculated_values(p, tmp_path)["Scorecard"]
    vals = {v[f"A{r}"].value: (v[f"B{r}"].value, v[f"C{r}"].value, v[f"D{r}"].value) for r in range(5, 12)}
    assert vals["Conforme"] == (1, 0, 1)
    assert vals["No conforme"] == (2, 0, 2)
    assert vals["No aplica"] == (0, 1, 1)
    assert vals["Sin respuesta"] == (0, 1, 1)
    assert vals["Total preguntas"] == (3, 2, 5)
    tr = wb["Matriz de trazabilidad"]
    row2 = [c.value for c in tr[2]]
    assert row2[0] == "Q1" and row2[5] == "TEST-INV-001"
    assert "H-001" in [c.value for c in tr[3]]


@needs_lo
def test_audit_excel_percentage_only_when_documented(ctx, loaded, audit, tmp_path):
    svc, aid = audit
    svc.set_methodology(aid, Methodology(name="Metodología de prueba", source="TEST-STD-001 numeral X (sintético)",
                                         compliant_values=["Conforme"], noncompliant_values=["No conforme"],
                                         allow_percentage=True))
    _fill(svc, aid, ctx, loaded)
    p = export_audit(ctx.db, aid, tmp_path / "auditoria_pct.xlsx")
    v = recalculated_values(p, tmp_path)["Scorecard"]
    pct_row = next(r for r in range(5, 20) if str(v[f"A{r}"].value).startswith("% conformidad"))
    assert abs(v[f"B{pct_row}"].value - 1 / 3) < 1e-9  # 1 conforme / (1 + 2)
    assert v[f"C{pct_row}"].value in (None, "")  # complementaria: 0/0 → vacío
