# Manual de usuario — SEMS AI Local Assistant

## 1. Primer uso
1. Ejecute `run_sems_ai.bat` (o `SEMS_AI.exe`).
2. La barra superior muestra **🔒 Offline** (conexiones externas bloqueadas) y el estado de la IA local.
   Si indica «Ollama no disponible», todo funciona salvo la redacción con IA y la búsqueda semántica.
3. Opcional: en **Configuración → Usuarios** cree usuarios y active «Requerir inicio de sesión».

## 2. Repositorio documental
- **Importar archivos / carpeta**: elija la categoría. Los originales se copian a la bóveda (solo lectura).
  Al terminar se informa: importados, duplicados (mismo SHA-256), rechazados (firma no coincide, ejecutables,
  ZIP inseguros) y archivos que requieren atención (no compatibles, pendientes de OCR).
- **Editar ficha**: código, revisión, fechas, estado, responsable de verificación. Un código detectado
  automáticamente queda anotado como «requiere verificación». Un estado «verificado» exige responsable.
- **Nueva versión**: agrega una revisión; las anteriores se conservan.
- **Verificar integridad**: recalcula el SHA-256 de todos los originales.
- **Buscar**: «Filtrar ficha» (nombre, código, revisión, fecha) o «Buscar en texto completo».

## 3. Asistente IA
1. Escriba la consulta; elija una categoría si desea acotar.
2. Con «Usar IA local» la respuesta se redacta con el modelo; sin ella se muestran los fragmentos (modo
   extractivo).
3. Pestaña **Fuentes**: documento, código, revisión, sección, página. Seleccione una fuente para verla en el
   **Visor de referencias**, «Ver página» (PDF) o «Abrir documento original».
4. Pestaña **Advertencias**: citas, numerales o códigos no verificados en las fuentes.
5. Si no hay respaldo, el asistente responde: *«No se ha encontrado evidencia documental suficiente en el
   repositorio para confirmar este requisito.»*

## 4. Análisis de cumplimiento
1. Elija documento de **Referencia** (estándar/SOP) y **Evaluado** (plan/procedimiento local).
2. «Ejecutar análisis». Cada requisito muestra numeral, resultado preliminar, evidencia (cita literal),
   brecha, recomendación y confianza.
3. Doble clic → **Revisión humana**: estado, resultado final, revisor y notas.
4. «Exportar matriz Excel» / «Reporte Word».

Recuerde: «No identificado en el documento» se refiere a la cobertura documental, no prueba incumplimiento
operativo.

## 5. Revisión de Word
1. Desde el análisis, «Ir a revisión de Word», o seleccione el documento y el análisis.
2. «Crear revisión y propuestas»: se crea una propuesta por requisito parcial o no identificado.
3. Para cada propuesta: **Aceptar / editar** (edite el texto; las plantillas deben reemplazarse),
   **Rechazar** o **Volver a pendiente**. «Cambio manual» permite agregar propuestas propias.
4. «Generar copia revisada»: crea `<nombre>_REVISADO_<fecha>.docx` en el directorio de exportación, con el
   texto aceptado resaltado en amarillo y un comentario de Word por cambio (motivo, requisito, fuente,
   numeral, justificación, clasificación), más `_registro_cambios.xlsx`. El original no se modifica.

## 6. Auditorías SEMS
1. **Nueva auditoría** (estándar, SOP, activo, alcance, fechas, auditor, auditados).
2. **Metodología**: escriba las opciones de respuesta y tipos de hallazgo del estándar aplicable y su fuente.
   Sin fuente no se calculan porcentajes.
3. **Importar checklist oficial** (Excel): indique la identificación del checklist y las columnas.
4. **Preguntas complementarias**: se generan desde los requisitos de un procedimiento y se etiquetan como no
   oficiales.
5. Registre respuestas, evidencias, hallazgos, acciones correctivas y seguimiento.
6. **Exportar Excel** (Cover, Checklist oficial, Revisión complementaria, Evidencias, Non-Compliance,
   Acciones correctivas, Scorecard, Matriz de trazabilidad, Informe ejecutivo) o **Informe Word**.

## 7. Gestión de desechos
Registre corrientes (la peligrosidad «Sí/No» exige base documental), movimientos por etapa (generación →
almacenamiento → transporte → tratamiento → disposición final), consulte la **Trazabilidad** y exporte el
Excel con balances calculados por fórmulas. Los formularios incluidos son internos, no oficiales.

## 8. Matriz legal
Registre instrumentos a partir de textos oficiales que disponga. El estado inicial es «No verificado»; para
marcar vigencia indique responsable y fundamento. Registre relaciones (reforma, deroga…) y obligaciones;
la pestaña **Advertencias** muestra contradicciones, versiones duplicadas y verificaciones desactualizadas.

## 9. Respaldos
**Configuración → Crear respaldo** (con contraseña = cifrado), **Verificar respaldo**, **Restaurar respaldo**
(en una carpeta nueva; para usarla defina `SEMS_AI_HOME`).
