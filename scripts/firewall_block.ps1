<#
  Defensa en profundidad: bloquea en el Firewall de Windows las conexiones salientes del
  ejecutable de SEMS AI hacia internet. Ejecutar como Administrador.
  Nota: el tráfico de bucle local (127.0.0.1, usado por Ollama) no es filtrado por el
  Firewall de Windows. Verifique la regla en su equipo tras crearla.
#>
param([string]$ExePath = (Join-Path $PSScriptRoot "..\dist\SEMS_AI\SEMS_AI.exe"))
$ExePath = (Resolve-Path $ExePath).Path
New-NetFirewallRule -DisplayName "SEMS AI - bloquear salida" -Direction Outbound -Program $ExePath `
    -Action Block -RemoteAddress Internet -Profile Any
Write-Host "Regla creada para $ExePath"
