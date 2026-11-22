<#
  Instalación OFFLINE de SEMS AI (sin internet), usando paquetes previamente descargados
  con scripts\download_offline_packages.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path "offline_packages")) { throw "No existe la carpeta offline_packages." }
$py = $null
foreach ($v in @("3.12", "3.11")) { try { $p = & py -$v -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0) { $py = $p; break } } catch {} }
if (-not $py) { throw "Instale Python 3.11 o 3.12 desde el instalador copiado." }
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_packages --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --no-index --find-links offline_packages -r requirements.txt
Write-Host "Instalación offline completada. Ejecute run_sems_ai.bat"
