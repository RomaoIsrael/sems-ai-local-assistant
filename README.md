# SEMS AI — Local Assistant

Aplicación de escritorio para Windows que gestiona documentación SEMS, HSE, ambiental y QA/QC
**completamente sin conexión**: repositorio documental, búsqueda, asistente con IA local (RAG con citas
verificables), análisis de brechas, revisión de Word con comentarios y resaltado, auditorías SEMS en Excel,
matriz legal y gestión de desechos.

> Versión 0.1.0 — primera versión funcional. Ver el estado real de cada módulo más abajo y en
> [docs/RESULTADOS_PRUEBAS.md](docs/RESULTADOS_PRUEBAS.md).

## Inicio rápido (Windows)

```powershell
# 1. Instalar (requiere internet solo en este paso)
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
# 2. Ejecutar
run_sems_ai.bat
```

- Instalación sin internet: [docs/INSTALACION_OFFLINE.md](docs/INSTALACION_OFFLINE.md)
- Generar el ejecutable `.exe`: [docs/COMPILACION_WINDOWS.md](docs/COMPILACION_WINDOWS.md)
- Manual de usuario: [docs/MANUAL_USUARIO.md](docs/MANUAL_USUARIO.md)
- Manual técnico (arquitectura, hardware, modelos): [docs/MANUAL_TECNICO.md](docs/MANUAL_TECNICO.md)
- Seguridad: [docs/SEGURIDAD.md](docs/SEGURIDAD.md)

La aplicación funciona **sin modelo de IA instalado**: el repositorio, la búsqueda de texto completo,
el análisis léxico de brechas, Word, Excel, auditorías, matriz legal y desechos siguen operativos.
Con [Ollama](https://ollama.com) y un modelo local se habilitan respuestas redactadas, análisis
asistido y búsqueda semántica.

## Estado de los módulos (v0.1.0)

| Módulo | Estado | Notas |
|---|---|---|
| Repositorio documental | Funcional | PDF, DOCX/DOCM, XLSX/XLSM, PPTX, TXT, CSV, HTML, XML, JSON, imágenes, ZIP. Bóveda de solo lectura con SHA-256, versiones, categorías ampliables, integridad. |
| OCR | Opcional | Requiere Tesseract instalado localmente. Sin él, las imágenes y PDF escaneados quedan como `pendiente_ocr`. No probado en este entorno (Tesseract no disponible). |
| Búsqueda | Funcional | Texto completo SQLite FTS5 (sin acentos), por ficha (nombre, código, revisión, fecha, categoría). Semántica opcional con embeddings de Ollama. |
| Asistente IA (RAG) | Funcional | Sin modelo: modo extractivo con citas. Con modelo: respuesta etiquetada + verificación posterior de citas, numerales y códigos. Probado contra un servidor que emula la API de Ollama, **no con un modelo real** (ver limitaciones). |
| Análisis de cumplimiento | Funcional | Extracción determinista de requisitos (deberá/debe/shall/must/should…), matriz de brechas, revisión humana, exportación Excel y reporte Word. |
| Revisor de Word | Funcional | Copia con inserciones resaltadas en amarillo y comentarios reales de Word; aprobación individual; registro de cambios. Acciones soportadas: insertar párrafo después de un ancla, añadir texto al final de un párrafo. **No** reemplaza ni elimina texto existente. |
| Auditorías SEMS | Funcional | Checklist oficial importado de Excel, preguntas complementarias etiquetadas, metodología configurable, hallazgos, acciones, Excel de 9 pestañas, informe Word. |
| Matriz legal | Funcional | Instrumentos, relaciones, verificación de vigencia con responsable y fundamento, advertencias de contradicción. **No incluye legislación precargada**. |
| Gestión de desechos | Funcional | Corrientes, movimientos, trazabilidad y balance, formularios internos configurables (modelo de datos), Excel con indicadores. |
| Reportes | Funcional | Reporte técnico de cumplimiento, informe de auditoría, bitácora, historial. |
| Seguridad | Funcional | Bloqueo de conexiones externas en el proceso, usuarios locales con roles, bitácora, respaldos cifrados, defensas ante ZIP/archivos maliciosos. |
| Interfaz | Funcional | CustomTkinter, 11 secciones, tareas en segundo plano con cancelación. Español completo; el inglés cubre menús y etiquetas principales. |

## Limitaciones conocidas

- **No se han procesado documentos corporativos reales**: no fueron proporcionados. Todas las pruebas usan
  documentos sintéticos con prefijo `TEST-` y la marca «DOCUMENTO SINTÉTICO DE PRUEBA».
- **La calidad de un modelo LLM real no fue evaluada** (el entorno de desarrollo no permite descargar
  Ollama ni modelos). Use *Configuración → Evaluar recuperación* con preguntas de referencia propias.
- El `.exe` de Windows no se generó en este entorno (Linux); la especificación PyInstaller se validó
  compilando y ejecutando el equivalente en Linux. Debe compilarse en Windows (ver documentación).
- La extracción de requisitos se basa en verbos de obligación; textos con redacción atípica pueden requerir
  revisión manual. Los numerales solo se registran si aparecen en el texto.
- La comparación léxica no es concluyente entre idiomas distintos (p. ej. estándar en inglés y plan en
  español): esos casos se marcan «Requiere validación adicional» salvo que se use la IA local.
- Los formularios de desechos son configurables por datos (JSON); la interfaz genera el formulario
  automáticamente, pero no hay editor visual de plantillas.

## Desarrollo y pruebas

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
python -m pytest -q            # las pruebas con LibreOffice/pantalla se omiten si no están disponibles
```

Estructura: `sems_ai/` (ui, core, llm, rag, repository, document_processing, compliance, word_review,
audits, excel, legal, environmental, reports, security, database, config), `tests/`, `scripts/`, `docs/`.
