import docx
import openpyxl
import pytest

from lo_utils import needs_lo, recalculated_values
from sems_ai.compliance.gap_analysis import GapAnalyzer
from sems_ai.database.db import Database
from sems_ai.environmental.waste import WasteError, WasteService
from sems_ai.legal.service import LegalError, LegalService
from sems_ai.reports.technical_report import audit_report, compliance_report
from sems_ai.security.auth import AuthError, AuthService
from sems_ai.security.backup import BackupError, create_backup, restore_backup, verify_backup


# ------------------------------------------------------------------ legal
def test_legal_never_auto_valid(ctx):
    lg = LegalService(ctx.db)
    a = lg.add_instrument("TEST-LEY-001", "Ley sintética de prueba")
    assert lg.instrument(a)["validity_status"] == "No verificado"
    with pytest.raises(LegalError):
        lg.add_instrument("TEST-LEY-002", "x", validity_status="Vigente (verificado)")
    with pytest.raises(LegalError):
        lg.set_validity(a, "Vigente (verificado)", "", "")


def test_legal_warnings(ctx):
    lg = LegalService(ctx.db)
    a = lg.add_instrument("TEST-AM-001", "Acuerdo sintético A", publication_date="2020-01-01")
    b = lg.add_instrument("TEST-AM-002", "Acuerdo sintético B")
    lg.set_validity(a, "Vigente (verificado)", "Abogado X", "Consulta a fuente oficial (prueba)")
    lg.add_relation(b, a, "deroga")
    lg.add_instrument("TEST-AM-001", "Acuerdo sintético A (otra versión)", publication_date="2021-05-05")
    tipos = {w["tipo"] for w in lg.warnings()}
    assert {"Contradicción", "Versiones contradictorias", "Sin verificar"} <= tipos


def test_legal_matrix_export(ctx, tmp_path):
    lg = LegalService(ctx.db)
    a = lg.add_instrument("TEST-RM-001", "Resolución sintética")
    o = lg.add_obligation(a, "Presentar informe anual sintético", "Art. 1")
    with pytest.raises(LegalError):
        lg.evaluate_obligation(o, "Cumple (verificado)", "Auditor", "")
    lg.evaluate_obligation(o, "Cumple (verificado)", "Auditor", "Oficio de prueba 123")
    p = lg.export_matrix(tmp_path / "matriz_legal.xlsx")
    wb = openpyxl.load_workbook(p)
    assert {"Matriz legal", "Instrumentos", "Relaciones", "Advertencias"} <= set(wb.sheetnames)


# ------------------------------------------------------------------ desechos
@needs_lo
def test_waste_traceability_and_excel(ctx, tmp_path):
    ws = WasteService(ctx.db)
    with pytest.raises(WasteError):
        ws.add_stream("D-01", "Aceite usado", hazardous="Sí")  # sin base documental
    s = ws.add_stream("D-01", "Aceite usado (sintético)", hazardous="Sí", classification_basis="Ficha de prueba")
    ws.add_movement(s, "2026-01-10", "Generación", 100)
    ws.add_movement(s, "2026-01-11", "Almacenamiento temporal", 100)
    _, w = ws.add_movement(s, "2026-01-20", "Transporte", 60)
    assert any("manifiesto" in x for x in w)
    ws.add_movement(s, "2026-01-21", "Disposición final", 60, manager="Gestor de prueba")
    tr = ws.traceability(s)
    assert tr["pendiente_destino"] == 40
    with pytest.raises(WasteError):
        ws.add_movement(s, "2026-01-22", "Transporte", 5, unit="t")
    p = ws.export_excel(tmp_path / "desechos.xlsx")
    v = recalculated_values(p, tmp_path)["Indicadores"]
    assert v["A4"].value == "D-01" and v["C4"].value == 100 and v["G4"].value == 60 and v["H4"].value == 40


def test_forms_internal_not_official(ctx):
    ws = WasteService(ctx.db)
    ws.ensure_default_forms()
    ts = ws.templates("desechos")
    assert ts and all(t["is_official"] == 0 for t in ts)
    with pytest.raises(WasteError):
        ws.create_template("Formato X", "desechos", [{"name": "a", "label": "A"}], is_official=True)
    t = ts[0]
    req = next(f for f in t["fields"] if f.get("required"))
    with pytest.raises(WasteError):
        ws.add_record(t["id"], {})
    data = {f["name"]: "x" for f in t["fields"] if f.get("required")}
    data[req["name"]] = "2026-01-01"
    assert ws.add_record(t["id"], data)


# ------------------------------------------------------------------ reportes
def test_reports(ctx, loaded, tmp_path):
    from sems_ai.audits.service import AuditService

    aid = GapAnalyzer(ctx.db).run(loaded["std"].version_id, loaded["plan"].version_id)
    p = compliance_report(ctx.db, aid, tmp_path / "rep.docx")
    text = "\n".join(x.text for x in docx.Document(p).paragraphs)
    assert "no prueba incumplimiento operativo" in text and "TEST-STD-001-R003" in text
    au = AuditService(ctx.db).create_audit("A1")
    p2 = audit_report(ctx.db, au, tmp_path / "aud.docx")
    assert "SEMS AI no genera conclusiones" in "\n".join(x.text for x in docx.Document(p2).paragraphs)
    with pytest.raises(FileExistsError):
        compliance_report(ctx.db, aid, p)


# ------------------------------------------------------------------ seguridad
def test_auth(ctx):
    auth = AuthService(ctx.db)
    with pytest.raises(AuthError):
        auth.create_user("ana", "corta", "auditor")
    auth.create_user("ana", "contraseña-segura-1", "lector")
    u = auth.authenticate("ana", "contraseña-segura-1")
    assert u.can("query") and not u.can("word.approve")
    with pytest.raises(AuthError):
        auth.authenticate("ana", "incorrecta-xxxx")
    assert ctx.db.query_one("SELECT COUNT(*) n FROM audit_log WHERE action='login.fail'")["n"] == 1


def test_backup_encrypted_roundtrip(ctx, loaded, tmp_path):
    bak = create_backup(ctx.settings, password="clave-de-prueba-123", dest_dir=tmp_path / "bk")
    assert bak.suffix == ".semsbak"
    assert b"TEST-STD-001" not in bak.read_bytes()  # contenido cifrado
    with pytest.raises(BackupError):
        verify_backup(bak, "otra")
    man = verify_backup(bak, "clave-de-prueba-123")
    assert "sems_ai.db" in man["files"] and any(k.startswith("vault/") for k in man["files"])
    target = restore_backup(bak, tmp_path / "restaurado", "clave-de-prueba-123")
    db2 = Database(target / "sems_ai.db")
    assert db2.query_one("SELECT COUNT(*) n FROM documents")["n"] == 3
    with pytest.raises(BackupError):
        restore_backup(bak, target, "clave-de-prueba-123")  # no sobrescribe sin confirmación


def test_backup_tamper_detected(ctx, loaded, tmp_path):
    bak = create_backup(ctx.settings, dest_dir=tmp_path / "bk")
    raw = bytearray(bak.read_bytes())
    raw[200] ^= 0xFF
    bak.write_bytes(bytes(raw))
    with pytest.raises(Exception):
        verify_backup(bak)


def test_error_recovery_db_rollback(ctx):
    """Un error a mitad de una transacción no deja datos parciales."""
    with pytest.raises(Exception):
        with ctx.db.connect() as c:
            c.execute("INSERT INTO categories(name) VALUES ('temporal-rollback')")
            raise RuntimeError("fallo simulado")
    assert ctx.db.query_one("SELECT COUNT(*) n FROM categories WHERE name='temporal-rollback'")["n"] == 0
