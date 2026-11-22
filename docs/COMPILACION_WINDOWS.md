# Generación del ejecutable de Windows

Requisitos: Windows 10/11 x64, Python 3.11/3.12, entorno `.venv` instalado (`scripts\install_windows.ps1`).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Resultado: `dist\SEMS_AI\SEMS_AI.exe` (modo carpeta, arranque rápido). Distribuya la carpeta completa
`dist\SEMS_AI\`. Tamaño aproximado: 250 MB (PyMuPDF, pandas y Tk incluidos).

Notas:
- `sems_ai.spec` incluye `schema.sql` y los recursos de CustomTkinter.
- El motor Ollama y los modelos **no** se incluyen: se instalan por separado (ver INSTALACION_OFFLINE.md).
- Antivirus corporativos pueden marcar ejecutables PyInstaller no firmados: se recomienda firmar
  `SEMS_AI.exe` con el certificado de la organización (`signtool sign /fd SHA256 ...`).
- Defensa en profundidad: `scripts\firewall_block.ps1` crea una regla de Firewall de salida para el `.exe`.

Verificación realizada en el entorno de desarrollo: la misma especificación se compiló con PyInstaller 6 en
Linux y el binario resultante arrancó la interfaz y creó la base de datos. **La compilación en Windows no
pudo ejecutarse en ese entorno** y debe verificarse en el equipo destino.
