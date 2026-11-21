import zipfile

import docx
import openpyxl
import pytest

from lo_utils import convert, needs_lo, recalculated_values
from sems_ai.compliance.export import export_gap_matrix
from sems_ai.compliance.gap_analysis import GapAnalyzer
from sems_ai.compliance.requirements import extract_requirements
from sems_ai.document_processing.safety import sha256_file
from sems_ai.word_review.service import ReviewError, WordReviewService


@pytest.fixture()
def analysis(ctx, loaded):
    ga = GapAnalyzer(ctx.db, username="tester")
    aid = ga.run(loaded["std"].version_id, loaded["plan"].version_id)
    return ga, aid


def test_requirements_have_real_numerals(ctx, loaded):
    from sems_ai.compliance.requirements import RequirementService

    reqs = RequirementService(ctx.db).extract_for_version(loaded["std"].version_id)
    by_num = {r["numeral"]: r for r in reqs}
    assert set(by_num) == {"1.2", "1.3", "1.4", "1.5", "1.6"}
    assert by_num["1.5"]["obligation_type"] == "Recomendado"
    assert by_num["1.4"]["obligation_type"] == "Obligatorio"
    corpus = " ".join(r["text"] for r in ctx.db.query("SELECT text FROM chunks WHERE version_id=?",
                                                        (loaded["std"].version_id,)))
    for n in by_num:  # ningún numeral inventado
        assert n in corpus


def test_requirement_without_numeral_left_empty():
    reqs = extract_requirements([{"id": 1, "text": "El contratista deberá entregar reportes mensuales de residuos.",
                                  "page": 3, "section": None}], "X")
    assert reqs and reqs[0].numeral is None and reqs[0].page == 3


def test_gap_results(analysis):
    ga, aid = analysis
    res = {i["numeral"]: i for i in ga.items(aid)}
    assert res["1.2"]["result"] == "Cubierto documentalmente"
    assert res["1.3"]["result"] == "Parcialmente cubierto"
    assert res["1.4"]["result"] == "No identificado en el documento"
    assert all(i["review_status"] == "Pendiente de revisión" for i in res.values())
    assert "no constituye prueba de cumplimiento operativo" in res["1.2"]["justification"]


def test_human_review_requires_reviewer(analysis):
    ga, aid = analysis
    item = ga.items(aid)[0]
    with pytest.raises(ValueError):
        ga.review(item["id"], "Validado por auditor", "")
    ga.review(item["id"], "Modificado por auditor", "Auditor X", result="Parcialmente cubierto", notes="ok")
    it = ga.items(aid)[0]
    assert it["review_status"] == "Modificado por auditor" and it["result"] == "Parcialmente cubierto"


@needs_lo
def test_gap_matrix_excel_formulas_and_validations(ctx, analysis, tmp_path):
    ga, aid = analysis
    p = export_gap_matrix(ctx.db, aid, tmp_path / "matriz.xlsx")
    wb = openpyxl.load_workbook(p)
    ws = wb["Matriz de brechas"]
    assert ws.data_validations.dataValidation, "faltan listas desplegables"
    assert wb["Resumen"]["B5"].value.startswith("=COUNTIF(")
    vals = recalculated_values(p, tmp_path)["Resumen"]
    counts = {vals[f"A{r}"].value: vals[f"B{r}"].value for r in range(5, 10)}
    assert counts["Cubierto documentalmente"] == 1
    assert counts["Parcialmente cubierto"] == 1
    assert counts["No identificado en el documento"] == 3
    assert vals["B10"].value == 5 and vals["B12"].value == 5
    assert abs(vals["C5"].value - 0.2) < 1e-9


# ------------------------------------------------------------------ Word
@pytest.fixture()
def generated(ctx, docs, analysis, tmp_path):
    ga, aid = analysis
    svc = WordReviewService(ctx.db, "Auditor Prueba", "AP")
    rid = svc.create_review(docs["plan_docx"], analysis_id=aid)
    n = svc.propose_from_analysis(rid, aid)
    assert n == 4  # 1 parcial + 3 no identificados
    chs = svc.changes(rid)
    with pytest.raises(ReviewError):  # la plantilla debe editarse antes de aceptar
        svc.decide(chs[0]["id"], "aceptada", "Auditor Prueba")
    svc.decide(chs[0]["id"], "aceptada", "Auditor Prueba",
               new_text="Las áreas de almacenamiento contarán además con piso impermeabilizado y cubeto de contención.")
    svc.decide(chs[1]["id"], "aceptada", "Auditor Prueba",
               new_text="Se auditará anualmente a los gestores ambientales y se conservarán las evidencias.")
    svc.decide(chs[2]["id"], "rechazada", "Auditor Prueba")
    before = sha256_file(docs["plan_docx"])
    res = svc.generate(rid, tmp_path / "out")
    return svc, rid, res, before, chs


def test_word_original_untouched_and_copy_created(docs, generated):
    svc, rid, res, before, _ = generated
    assert sha256_file(docs["plan_docx"]) == before
    assert res.output_path.exists() and res.output_path != docs["plan_docx"]
    assert res.applied == 2


def test_word_structure_preserved(docs, generated):
    _, _, res, _, _ = generated
    a, b = docx.Document(docs["plan_docx"]), docx.Document(res.output_path)
    assert len(b.tables) == len(a.tables) and b.tables[0].cell(1, 1).text == "Aceite usado"
    assert len(b.inline_shapes) == len(a.inline_shapes) == 1
    assert b.sections[0].header.paragraphs[0].text == a.sections[0].header.paragraphs[0].text
    assert b.sections[0].footer.paragraphs[0].text == a.sections[0].footer.paragraphs[0].text
    assert len(b.paragraphs) == len(a.paragraphs) + 2
    # los párrafos originales mantienen texto, estilo y sangría en el mismo orden
    orig = [(p.text, p.style.name, p.paragraph_format.left_indent) for p in a.paragraphs]
    new = [(p.text, p.style.name, p.paragraph_format.left_indent) for p in b.paragraphs]
    it = iter(new)
    assert all(any(o == n for n in it) for o in orig)


def test_word_highlight_and_comments(generated):
    _, _, res, _, chs = generated
    d = docx.Document(res.output_path)
    inserted = [p for p in d.paragraphs if "cubeto de contención" in p.text and "además" in p.text]
    assert inserted
    run = inserted[0].runs[0]
    assert str(run.font.highlight_color) .startswith("YELLOW")
    assert inserted[0].paragraph_format.left_indent == d.paragraphs[[p.text for p in d.paragraphs].index(
        inserted[0].text) - 1].paragraph_format.left_indent  # copia la sangría del ancla
    comments = list(d.comments)
    assert len(comments) == 2
    txt = comments[0].text + comments[1].text
    for label in ("Motivo:", "Requisito relacionado:", "Fuente documental:", "Numeral aplicable:",
                  "Justificación técnica:", "Clasificación:"):
        assert label in txt
    with zipfile.ZipFile(res.output_path) as z:
        xml = z.read("word/document.xml").decode()
        assert "w:commentRangeStart" in xml and "w:commentReference" in xml and 'w:highlight w:val="yellow"' in xml


@needs_lo
def test_word_comments_visible_in_other_processor(generated, tmp_path):
    _, _, res, _, _ = generated
    odt = convert(res.output_path, "odt", tmp_path / "lo")
    with zipfile.ZipFile(odt) as z:
        content = z.read("content.xml").decode()
    assert content.count("<office:annotation") >= 2
    assert "Numeral aplicable" in content


def test_change_log_excel(generated):
    _, _, res, _, _ = generated
    wb = openpyxl.load_workbook(res.log_path)
    ws = wb["Registro de modificaciones"]
    decisions = [ws.cell(row=r, column=2).value for r in range(9, 13)]
    assert decisions.count("aceptada") == 2 and "rechazada" in decisions


def test_generate_refuses_changed_source(ctx, docs, analysis, tmp_path):
    import shutil

    p = tmp_path / "copia.docx"
    shutil.copy(docs["plan_docx"], p)
    svc = WordReviewService(ctx.db)
    rid = svc.create_review(p)
    d = docx.Document(p)
    d.add_paragraph("cambio externo")
    d.save(p)
    with pytest.raises(ReviewError):
        svc.generate(rid, tmp_path / "o")
