# Seguridad

| Control | Implementación |
|---|---|
| Procesamiento local | Sin APIs de pago ni servicios en la nube. El cliente LLM rechaza URLs que no sean 127.0.0.1/localhost/::1. |
| Bloqueo de conexiones salientes | `security/network_guard.py` intercepta `socket.connect`, `connect_ex` y `getaddrinfo`: cualquier host no local genera `OfflineViolation`. Activo por defecto. Complementar con `scripts/firewall_block.ps1`. |
| Protección de originales | Copia a la bóveda con nombre SHA-256, verificación de la copia, atributo solo lectura. Las revisiones de Word trabajan sobre copias y validan el hash del original antes y después. Excel/Word exportados nunca sobrescriben archivos existentes. |
| Integridad | «Verificar integridad» recalcula SHA-256 de todos los originales (OK / ALTERADO / FALTA). |
| Documentos maliciosos | Firma binaria vs. extensión, rechazo de ejecutables, límite de tamaño, detección de macros VBA/ActiveX/objetos incrustados (nunca se ejecutan), detección de JavaScript/Launch/OpenAction en PDF, ZIP: anti *zip-slip*, límite de tamaño y relación de compresión, archivos máximos, profundidad máxima, ZIP cifrados rechazados. XML sin resolución de entidades externas. |
| Control de acceso | Usuarios locales, PBKDF2-HMAC-SHA256 (310 000 iteraciones, sal aleatoria), roles admin/auditor/editor/lector. Inicio de sesión opcional. |
| Registro | Tabla `audit_log`: importaciones, rechazos, cambios de ficha, decisiones de revisión, aprobaciones Word, inicios de sesión. Exportable. |
| Respaldo | ZIP con manifiesto SHA-256; cifrado opcional Fernet (AES-128-CBC + HMAC) con clave PBKDF2 (600 000 iteraciones). Restauración sin borrar datos previos. |
| Aprobación humana | Resultados de cumplimiento «Pendiente de revisión»; cambios Word solo con aceptación individual identificada. |

Limitaciones:
- El bloqueo de red protege el proceso Python de SEMS AI; no controla otros programas (p. ej. el propio
  servicio Ollama). Configure Ollama sin acceso a internet tras descargar los modelos (Firewall).
- La base SQLite no está cifrada en reposo: use BitLocker o equivalente en el equipo.
- Los roles se aplican en la interfaz y servicios; un usuario con acceso al sistema de archivos puede leer
  la base de datos directamente.
