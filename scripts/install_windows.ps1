<#
  Instalación ONLINE de SEMS AI en Windows (requiere internet solo durante la instalación).
  Uso (PowerShell, en la carpeta del proyecto):
      powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Find-Python {
    foreach ($v in @("3.12", "3.11")) {
        try { $p = & py -$v -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0) { return $p } } catch {}
    }
    throw "No se encontró Python 3.11 o 3.12. Instálelo desde python.org (marcar 'tcl/tk and IDLE')."
}

$py = Find-Python
Write-Host "Python: $py"
& $py -c "import tkinter" ; if ($LASTEXITCODE -ne 0) { throw "Tkinter no está disponible en esta instalación de Python." }
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "Dependencias instaladas."

# Motor de IA local (opcional)
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) {
    Write-Host "Ollama detectado. Modelos recomendados (ver docs\MANUAL_TECNICO.md):"
    Write-Host "   ollama pull qwen2.5:7b-instruct"
    Write-Host "   ollama pull bge-m3"
} else {
    Write-Host "Ollama no está instalado: la biblioteca y la búsqueda funcionarán sin IA generativa."
    Write-Host "Para habilitar IA local instale Ollama para Windows (ver docs\INSTALACION_OFFLINE.md)."
}
Write-Host "Ejecute la aplicación con run_sems_ai.bat"
