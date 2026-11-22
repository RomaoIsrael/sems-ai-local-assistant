# Resultados de pruebas — v0.1.0

Ejecutado el 2026-11-22 en el entorno de desarrollo: Linux x86_64, Python 3.12.3, LibreOffice 24.2.7
(recálculo de fórmulas y apertura de comentarios), Xvfb (interfaz). Comando: `python -m pytest -v`.

**Resultado: 55 aprobadas, 0 fallidas, 0 omitidas.**

Todas las pruebas se ejecutan con el bloqueo de conexiones externas ACTIVO y con documentos sintéticos
(`TEST-*`). No se usaron documentos corporativos reales (no fueron proporcionados).

## Verificaciones explícitas solicitadas

| # | Requisito | Prueba(s) | Resultado |
|---|---|---|---|
| 1 | Funciona sin internet | `test_offline_guard_blocks_external` (conexión y DNS externos bloqueados; localhost permitido); toda la batería corre con el bloqueo activo; `test_llm_absent_app_still_works` | Aprobada |
| 2 | Los originales no se modifican | `test_originals_not_modified_and_vault_readonly`, `test_word_original_untouched_and_copy_created`, `test_generate_refuses_changed_source` | Aprobada |
| 3 | Referencias trazables | `test_fulltext_search_finds_page` (documento, código, página), `test_extractive_mode_without_llm`, `test_requirements_have_real_numerals`, `test_audit_excel_provisional` (matriz de trazabilidad) | Aprobada |
| 4 | No inventa códigos normativos | `test_llm_invented_code_and_numeral_flagged`, `test_gap_llm_rejects_invented_quote`, `test_requirement_without_numeral_left_empty` | Aprobada |
| 5 | Word mantiene su estructura | `test_word_structure_preserved` (tablas, imagen, encabezado, pie, estilos, sangrías, orden) | Aprobada |
| 6 | Comentarios de Word visibles | `test_word_highlight_and_comments` (comments.xml, anclas), `test_word_comments_visible_in_other_processor` (LibreOffice convierte a ODT con 2 anotaciones) | Aprobada |
| 7 | Excel conserva fórmulas y validaciones | `test_gap_matrix_excel_formulas_and_validations`, `test_audit_excel_provisional`, `test_audit_excel_percentage_only_when_documented`, `test_waste_traceability_and_excel` (valores recalculados por LibreOffice contra datos conocidos) | Aprobada |
| 8 | Resultados de auditoría persisten | `test_results_persist` (nueva conexión a la base) | Aprobada |
| 9 | Nuevas versiones no eliminan anteriores | `test_new_version_keeps_previous` | Aprobada |
| 10 | Errores comunicados claramente | `test_unsupported_and_renamed_files`, `test_zip_import_and_zip_slip_rejected`, `test_error_recovery_db_rollback`, mensajes de `AuditError`/`ReviewError`/`LegalError`/`WasteError` | Aprobada |

## Lo que NO fue probado en este entorno

- Un modelo LLM real con Ollama (descarga bloqueada por la red del entorno). La integración se probó con un
  servidor local que reproduce la API HTTP de Ollama (`tests/test_ollama_protocol.py`): estado, streaming,
  embeddings, búsqueda híbrida, validación de respuestas y descarte de citas inventadas. La calidad de las
  respuestas de un modelo real debe medirse con el módulo de evaluación y preguntas de referencia propias.
- OCR con Tesseract (no instalado): solo se verificó que las imágenes quedan como `pendiente_ocr`.
- Compilación y ejecución en Windows: la especificación PyInstaller se compiló y ejecutó en Linux.
- Microsoft Word/Excel: la compatibilidad se verificó con python-docx/openpyxl y LibreOffice.
- Los documentos de validación indicados (APS-SEMS-ST-001, SPM-SEMS-SOP-001, etc.) no estaban disponibles.

## Detalle
```
tests/test_audits.py::test_official_vs_complementary PASSED
tests/test_audits.py::test_methodology_rules PASSED
tests/test_audits.py::test_results_persist PASSED
tests/test_audits.py::test_audit_excel_provisional PASSED
tests/test_audits.py::test_audit_excel_percentage_only_when_documented PASSED
tests/test_compliance_word.py::test_requirements_have_real_numerals PASSED
tests/test_compliance_word.py::test_requirement_without_numeral_left_empty PASSED
tests/test_compliance_word.py::test_gap_results PASSED
tests/test_compliance_word.py::test_human_review_requires_reviewer PASSED
tests/test_compliance_word.py::test_gap_matrix_excel_formulas_and_validations PASSED
tests/test_compliance_word.py::test_word_original_untouched_and_copy_created PASSED
tests/test_compliance_word.py::test_word_structure_preserved PASSED
tests/test_compliance_word.py::test_word_highlight_and_comments PASSED
tests/test_compliance_word.py::test_word_comments_visible_in_other_processor PASSED
tests/test_compliance_word.py::test_change_log_excel PASSED
tests/test_compliance_word.py::test_generate_refuses_changed_source PASSED
tests/test_ollama_protocol.py::test_status_and_stream PASSED
tests/test_ollama_protocol.py::test_semantic_hybrid_search PASSED
tests/test_ollama_protocol.py::test_rag_with_llm_streaming_and_validation PASSED
tests/test_ollama_protocol.py::test_gap_llm_rejects_invented_quote PASSED
tests/test_ollama_protocol.py::test_gap_llm_accepts_literal_quote PASSED
tests/test_phase6_security.py::test_legal_never_auto_valid PASSED
tests/test_phase6_security.py::test_legal_warnings PASSED
tests/test_phase6_security.py::test_legal_matrix_export PASSED
tests/test_phase6_security.py::test_waste_traceability_and_excel PASSED
tests/test_phase6_security.py::test_forms_internal_not_official PASSED
tests/test_phase6_security.py::test_reports PASSED
tests/test_phase6_security.py::test_auth PASSED
tests/test_phase6_security.py::test_backup_encrypted_roundtrip PASSED
tests/test_phase6_security.py::test_backup_tamper_detected PASSED
tests/test_phase6_security.py::test_error_recovery_db_rollback PASSED
tests/test_repository.py::test_import_pdf_docx_xlsx PASSED
tests/test_repository.py::test_code_detected_and_flagged_for_verification PASSED
tests/test_repository.py::test_originals_not_modified_and_vault_readonly PASSED
tests/test_repository.py::test_duplicate_detection PASSED
tests/test_repository.py::test_new_version_keeps_previous PASSED
tests/test_repository.py::test_integrity_detects_tampering PASSED
tests/test_repository.py::test_unsupported_and_renamed_files PASSED
tests/test_repository.py::test_image_pending_ocr PASSED
tests/test_repository.py::test_zip_import_and_zip_slip_rejected PASSED
tests/test_repository.py::test_macro_flag PASSED
tests/test_repository.py::test_folder_import_with_cancel PASSED
tests/test_repository.py::test_custom_category_and_metadata PASSED
tests/test_search_rag.py::test_fulltext_search_finds_page PASSED
tests/test_search_rag.py::test_accent_insensitive PASSED
tests/test_search_rag.py::test_no_evidence_message PASSED
tests/test_search_rag.py::test_extractive_mode_without_llm PASSED
tests/test_search_rag.py::test_llm_invented_code_and_numeral_flagged PASSED
tests/test_search_rag.py::test_llm_grounded_answer_has_no_warnings PASSED
tests/test_search_rag.py::test_validate_answer_no_citations PASSED
tests/test_search_rag.py::test_offline_guard_blocks_external PASSED
tests/test_search_rag.py::test_llm_client_rejects_remote_host PASSED
tests/test_search_rag.py::test_llm_absent_app_still_works PASSED
tests/test_search_rag.py::test_evaluation_metrics PASSED
tests/test_ui_smoke.py::test_all_pages_render_and_query_runs_in_background PASSED
============================= 55 passed in 12.68s ==============================
```
