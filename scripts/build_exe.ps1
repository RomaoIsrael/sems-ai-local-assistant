<#
  Genera el ejecutable de Windows con PyInstaller (carpeta dist\SEMS_AI\SEMS_AI.exe).
  El motor Ollama y los modelos se distribuyen por separado.
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& .\.venv\Scripts\python.exe -m pip install pyinstaller
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean sems_ai.spec
Write-Host "Ejecutable: dist\SEMS_AI\SEMS_AI.exe"
