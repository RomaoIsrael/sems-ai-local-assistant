import os
import stat
import zipfile

from sems_ai.document_processing.safety import sha256_file


def test_import_pdf_docx_xlsx(ctx, loaded):
    for k in ("std", "plan", "xlsx"):
        assert loaded[k].status == "importado", loaded[k]
        assert loaded[k].extraction_status == "ok", loaded[k]
    stats = ctx.repository.stats()
    assert stats["documentos"] == 3
    assert stats["fragmentos"] > 3


def test_code_detected_and_flagged_for_verification(ctx, loaded):
    d = ctx.repository.get_document(loaded["std"].document_id)
    assert d["doc_code"] == "TEST-STD-001"
    assert "requiere verificación" in d["notes"]


def test_originals_not_modified_and_vault_readonly(ctx, docs, loaded):
    before = {k: sha256_file(p) for k, p in docs.items()}
    mtimes = {k: os.stat(p).st_mtime for k, p in docs.items()}
    ctx.repository.reprocess(loaded["plan"].version_id)
    for k, p in docs.items():
        assert sha256_file(p) == before[k]
        assert os.stat(p).st_mtime == mtimes[k]
    stored = ctx.repository.stored_file(loaded["plan"].version_id)
    assert not (os.stat(stored).st_mode & stat.S_IWUSR)
    assert sha256_file(stored) == before["plan_docx"]


def test_duplicate_detection(ctx, docs, loaded):
    again = ctx.repository.import_file(docs["plan_docx"])
    assert again.status == "duplicado"


def test_new_version_keeps_previous(ctx, docs, loaded, tmp_path):
    import docx

    d = docx.Document(docs["plan_docx"])
    d.add_paragraph("Revisión 1: se agrega texto nuevo de prueba.")
    p2 = tmp_path / "plan_rev1.docx"
    d.save(p2)
    out = ctx.repository.import_file(p2, metadata={"revision": "1"}, document_id=loaded["plan"].document_id)
    assert out.status == "nueva_version"
    vers = ctx.repository.versions(loaded["plan"].document_id)
    assert [v["version_no"] for v in vers] == [1, 2]
    assert all(ctx.repository.stored_file(v["id"]).exists() for v in vers)
    doc = ctx.repository.get_document(loaded["plan"].document_id)
    assert doc["current_version_id"] == out.version_id and doc["revision"] == "1"


def test_integrity_detects_tampering(ctx, loaded):
    res = ctx.repository.verify_integrity()
    assert all(r["estado"] == "OK" for r in res)
    p = ctx.repository.stored_file(loaded["xlsx"].version_id)
    os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
    with open(p, "ab") as fh:
        fh.write(b"tamper")
    res = {r["version_id"]: r["estado"] for r in ctx.repository.verify_integrity()}
    assert res[loaded["xlsx"].version_id] == "ALTERADO"


def test_unsupported_and_renamed_files(ctx, tmp_path):
    f = tmp_path / "datos.xyz"
    f.write_text("contenido")
    out = ctx.repository.import_file(f)
    assert out.status == "importado" and out.extraction_status == "no_compatible"
    fake = tmp_path / "falso.pdf"
    fake.write_bytes(b"MZ\x90\x00 esto no es un pdf")
    out = ctx.repository.import_file(fake)
    assert out.status == "rechazado"


def test_image_pending_ocr(ctx, tmp_path):
    from synthetic_docs import _png_bytes

    f = tmp_path / "escaneo.png"
    f.write_bytes(_png_bytes())
    out = ctx.repository.import_file(f)
    assert out.extraction_status in ("pendiente_ocr", "ok")  # ok solo si Tesseract está instalado


def test_zip_import_and_zip_slip_rejected(ctx, docs, tmp_path):
    z = tmp_path / "paquete.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(docs["xlsx"], "sub/inventario.xlsx")
    outs = ctx.repository.import_paths([z])
    assert any(o.extraction_status == "contenedor" for o in outs)
    assert any(o.status == "importado" and o.path.endswith("inventario.xlsx") for o in outs)
    evil = tmp_path / "malo.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", "x")
    outs = ctx.repository.import_paths([evil])
    assert "Ruta insegura" in outs[0].message
    assert not (tmp_path.parent / "escape.txt").exists()


def test_macro_flag(ctx, tmp_path, docs):
    import shutil

    p = tmp_path / "con_macro.xlsm"
    shutil.copy(docs["xlsx"], p)
    with zipfile.ZipFile(p, "a") as zf:
        zf.writestr("xl/vbaProject.bin", b"\x00fake")
    out = ctx.repository.import_file(p)
    assert any("macros" in f for f in out.flags)


def test_folder_import_with_cancel(ctx, docs):
    import pytest

    from sems_ai.repository.service import CancelledError

    with pytest.raises(CancelledError):
        ctx.repository.import_paths([docs["plan_docx"].parent], cancel=lambda: True)


def test_custom_category_and_metadata(ctx, loaded):
    repo = ctx.repository
    repo.add_category("Integridad de activos")
    repo.update_metadata(loaded["plan"].document_id, {"category": "Integridad de activos", "area": "HSE",
                                                      "status": "Vigente (verificado)"})
    d = repo.get_document(loaded["plan"].document_id)
    assert d["category"] == "Integridad de activos" and d["area"] == "HSE"
    assert repo.list_documents(text="TEST-PLAN")[0]["id"] == loaded["plan"].document_id
