# Procedimiento de instalación offline

## A. En un equipo con internet (preparación)
1. Copie el proyecto completo.
2. Ejecute `powershell -ExecutionPolicy Bypass -File scripts\download_offline_packages.ps1`
   → crea `offline_packages\` con las ruedas de Windows x64 para Python 3.11 y 3.12.
3. Descargue y guarde junto al proyecto:
   - Instalador de Python 3.11 o 3.12 para Windows x64 (python.org), con Tcl/Tk.
   - Opcional IA: `OllamaSetup.exe` (ollama.com/download/windows).
   - Opcional IA: en ese mismo equipo ejecute `ollama pull qwen2.5:7b-instruct` y `ollama pull bge-m3`;
     copie la carpeta `%USERPROFILE%\.ollama\models`.
   - Opcional OCR: instalador de Tesseract-OCR para Windows con idiomas `spa` y `eng`.
4. Verifique los instaladores (firma/hash del proveedor) antes de trasladarlos.

## B. En el equipo sin internet
1. Instale Python (marque «tcl/tk and IDLE» y «py launcher»).
2. En la carpeta del proyecto: `powershell -ExecutionPolicy Bypass -File scripts\install_offline.ps1`.
3. Opcional IA: instale Ollama y copie la carpeta `models` a `%USERPROFILE%\.ollama\models`.
   Compruebe con `ollama list`. Ollama escucha en `127.0.0.1:11434` (solo local).
4. Opcional OCR: instale Tesseract; si no queda en `C:\Program Files\Tesseract-OCR`, indique la ruta en
   Configuración.
5. Ejecute `run_sems_ai.bat`.

Alternativa: distribuya la carpeta `dist\SEMS_AI\` generada con PyInstaller (no requiere Python).

## C. Verificación
- La barra superior debe mostrar **🔒 Offline**.
- Configuración → «Probar IA local» debe indicar el modelo activo (si se instaló).
- Ejecute `python -m pytest -q` (si instaló `requirements-dev.txt`) para verificar la instalación.
