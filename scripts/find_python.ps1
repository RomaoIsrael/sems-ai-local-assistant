# Localiza un Python 3.11, 3.12 o 3.13 utilizable (con Tkinter). Uso: . .\scripts\find_python.ps1; $py = Find-SemsPython
function Test-SemsPython([string]$exe) {
    $ErrorActionPreference = "Continue"
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like "*\WindowsApps\*") { return $false }   # acceso directo de Microsoft Store, no es Python real
    try { $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { return $false }
    return ($LASTEXITCODE -eq 0 -and @("3.11", "3.12", "3.13") -contains "$v")
}

function Find-SemsPython {
    $ErrorActionPreference = "Continue"
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("3.12", "3.11", "3.13")) {
            try { $p = & py -$v -c "import sys; print(sys.executable)" 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0) { $candidates += $p }
        }
    }
    foreach ($name in @("python", "python3")) {
        Get-Command $name -All -ErrorAction SilentlyContinue | ForEach-Object { $candidates += $_.Source }
    }
    foreach ($v in @("312", "311", "313")) {
        $candidates += "$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe"
        $candidates += "$env:ProgramFiles\Python$v\python.exe"
        $candidates += "C:\Python$v\python.exe"
    }
    foreach ($c in $candidates) { if (Test-SemsPython $c) { return $c } }
    Write-Host ""
    Write-Host "No se encontró Python 3.11, 3.12 o 3.13." -ForegroundColor Red
    Write-Host "Candidatos revisados:"; $candidates | Select-Object -Unique | ForEach-Object { Write-Host "   $_" }
    Write-Host "Instale Python 3.12 (python.org o el portal de software de su empresa) marcando 'tcl/tk and IDLE'"
    Write-Host "y 'Add python.exe to PATH'. Luego cierre y vuelva a abrir PowerShell."
    throw "Python no encontrado"
}
