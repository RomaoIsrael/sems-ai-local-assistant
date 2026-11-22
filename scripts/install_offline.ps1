<#
  Instalación OFFLINE de SEMS AI (sin internet), usando paquetes previamente descargados
  con scripts\download_offline_packages.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path "offline_packages")) { throw "No existe la carpeta offline_packages." }
. (Join-Path $PSScriptRoot "find_python.ps1")
$py = Find-SemsPython
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_packages --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_packages -r requirements.txt
Write-Host "Instalación offline completada. Ejecute run_sems_ai.bat"
