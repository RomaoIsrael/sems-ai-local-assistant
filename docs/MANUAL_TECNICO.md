# Manual técnico — SEMS AI Local Assistant v0.1.0

## 1. Evaluación de necesidades y hardware

| Componente | Mínimo (sin IA generativa) | Recomendado (IA local 7B) | Alto rendimiento |
|---|---|---|---|
| SO | Windows 10/11 64 bits | Windows 10/11 64 bits | Windows 11 |
| CPU | 4 núcleos | 8 núcleos (AVX2) | 8+ núcleos |
| RAM | 8 GB | 16 GB | 32 GB |
| GPU | No requerida | Opcional (NVIDIA 8 GB acelera ~5–10×) | NVIDIA 12–16 GB |
| Disco | 2 GB + documentos | 10 GB + documentos | 20 GB + documentos |

Modelos sugeridos en Ollama (selección según RAM; deben validarse con el conjunto de evaluación propio):

| RAM disponible | Modelo de generación | Tamaño aprox. (Q4) | Embeddings |
|---|---|---|---|
| 8 GB | `qwen2.5:3b-instruct` o `llama3.2:3b` | ~2 GB | `bge-m3` (~1.2 GB) |
| 16 GB | `qwen2.5:7b-instruct` (predeterminado) | ~4.7 GB | `bge-m3` |
| 32 GB / GPU | `qwen2.5:14b-instruct` | ~9 GB | `bge-m3` |

`bge-m3` es multilingüe, útil cuando el estándar está en inglés y el plan local en español.
En CPU, un modelo 7B genera aproximadamente 3–8 tokens/s: una respuesta tarda entre 30 s y 2 min. La
interfaz no se bloquea durante ese tiempo.

## 2. Arquitectura

```
ui (CustomTkinter)  ──►  core (contexto, tareas en 2º plano, i18n)
        │                      │
        ▼                      ▼
 servicios de dominio: repository · rag · compliance · word_review · audits · legal · environmental · reports
        │                      │
        ▼                      ▼
 document_processing (extractores, chunker, seguridad)   llm (cliente Ollama solo-local)
        │
        ▼
 database (SQLite + FTS5)        security (bloqueo de red, usuarios, respaldo cifrado)
```

- La interfaz solo llama a servicios; los servicios no dependen de la interfaz (se prueban sin pantalla).
- Cada servicio abre su propia conexión SQLite (WAL) → seguro para hilos de trabajo.
- `core/tasks.py` ejecuta operaciones largas en hilos con progreso y cancelación; la UI consulta una cola.

### Datos

Directorio de datos: `%LOCALAPPDATA%\SEMS_AI` (o la variable `SEMS_AI_HOME`).

```
SEMS_AI/
  config.json      configuración
  sems_ai.db       base SQLite (esquema en sems_ai/database/schema.sql)
  vault/ab/<sha256>.<ext>   originales, solo lectura
  exports/         productos generados
  backups/         respaldos (.zip / .semsbak)
  logs/sems_ai.log
```

Tablas principales: `documents`, `document_versions`, `chunks` (+ `chunks_fts` FTS5), `embeddings`,
`requirements`, `compliance_analyses`, `compliance_items`, `word_reviews`, `word_review_changes`, `audits`,
`audit_questions`, `audit_evidence`, `audit_findings`, `corrective_actions`, `legal_instruments`,
`legal_relations`, `legal_obligations`, `waste_streams`, `waste_movements`, `form_templates`, `form_records`,
`query_history`, `audit_log`, `users`.

## 3. Flujo RAG

1. Consulta → `Retriever.search`: FTS5/BM25 (siempre) + coseno sobre embeddings (si están habilitados),
   fusionados por *Reciprocal Rank Fusion*.
2. Pertinencia: se descartan fragmentos con cobertura de términos < 25 % (umbral configurable en código).
3. Sin fragmentos pertinentes → respuesta literal: *«No se ha encontrado evidencia documental suficiente
   en el repositorio para confirmar este requisito.»* El modelo no se invoca.
4. Con modelo: prompt con fuentes `[S1]…[Sn]` y metadatos (código, revisión, sección, página, si el
   instrumento legal está verificado). Etiquetas obligatorias: REQUISITO DOCUMENTADO, OBLIGACIÓN LEGAL
   VERIFICADA, INTERPRETACIÓN TÉCNICA, RECOMENDACIÓN, BUENA PRÁCTICA, PENDIENTE DE VALIDAR.
5. Validación posterior (`rag/answer.py: validate_answer`): citas inexistentes, numerales que no aparecen en
   las fuentes, códigos documentales inexistentes en el repositorio, proporción de frases sin cita.
6. Se guarda en `query_history` con las fuentes y advertencias.

Sin modelo, el modo extractivo muestra los fragmentos citados sin interpretación.

### Evaluación

`rag/evaluation.py` calcula tasa de acierto, MRR, cobertura de términos, exactitud en casos «sin evidencia»
y número de advertencias. Plantilla: `config/evaluacion_plantilla.json`. Las preguntas y respuestas de
referencia deben prepararlas especialistas a partir de los documentos reales.

## 4. Análisis de cumplimiento

- `compliance/requirements.py`: segmenta por numerales que aparecen en el texto y extrae frases con verbos de
  obligación (Obligatorio, Recomendado, Prohibición). Numeral vacío si no se identifica.
- `compliance/gap_analysis.py`:
  - Modo léxico: cobertura de términos clave (≥60 % cubierto, 35–60 % parcial, <35 % no identificado).
    Si los idiomas difieren → «Requiere validación adicional».
  - Modo IA: el modelo devuelve JSON con cita literal; si la cita no existe en el documento local se descarta
    y el resultado pasa a «Requiere validación adicional». La confianza nunca supera «Media» sin revisión humana.
  - Todo ítem inicia en «Pendiente de revisión»; la revisión exige identificar al revisor.

## 5. Revisor de Word

`word_review/docx_editor.py` inserta un nuevo `w:p` después del párrafo ancla copiando su `w:pPr`
(sangrías, espaciado, alineación, numeración de listas) y el `w:rPr` del primer run (fuente, tamaño).
Si el ancla es un título, el nuevo párrafo usa el estilo normal. El run insertado lleva
`w:highlight=yellow` y un comentario real (`comments.xml`, API `Document.add_comment` de python-docx ≥ 1.2).
La copia se crea con `shutil.copy2` antes de editar; el SHA-256 del original se comprueba antes y después.

## 6. Auditorías

`audits/service.py` aplica las reglas: preguntas oficiales solo con referencia del checklist (archivo +
SHA-256 + fila), complementarias etiquetadas, respuestas y tipos de hallazgo restringidos a la metodología.
`audits/excel_export.py` genera 9 pestañas; el Scorecard usa `COUNTIF` y solo agrega `% conformidad` si la
metodología lo autoriza con fuente documental.

## 7. Extensión a otras disciplinas

- Nuevas categorías desde la interfaz (QA/QC, integridad de activos, operaciones, mantenimiento…).
- Nuevos formularios: `WasteService.create_template(name, module, fields)`; el campo `module` permite otras
  disciplinas.
- Nuevos extractores: agregar la extensión en `EXTRACTORS` (`document_processing/extractors.py`).
- Nuevos verbos de obligación: `OBLIGATION_PATTERNS` en `compliance/requirements.py`.

## 8. Pruebas

```
python -m pytest -q
```
Las pruebas que requieren LibreOffice (recálculo de fórmulas, apertura de comentarios en otro procesador)
o pantalla (interfaz) se omiten automáticamente si no están disponibles. Resultados reales en
`docs/RESULTADOS_PRUEBAS.md`.
