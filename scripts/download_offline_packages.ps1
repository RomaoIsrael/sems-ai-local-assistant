<#
  Prepara un paquete de instalación OFFLINE (ejecutar en un equipo CON internet).
  Descarga las ruedas (wheels) de Windows x64 para Python 3.11 y 3.12 en .\offline_packages
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force offline_packages | Out-Null
foreach ($v in @("311", "312")) {
    py -m pip download -r requirements.txt -d offline_packages --only-binary=:all: `
        --platform win_amd64 --python-version $v --implementation cp
}
py -m pip download pip setuptools wheel -d offline_packages
Write-Host "Listo. Copie la carpeta del proyecto (incluida offline_packages) al equipo sin internet."
Write-Host "Copie también: instalador de Python 3.11/3.12, OllamaSetup.exe y la carpeta de modelos (%USERPROFILE%\.ollama\models)."
