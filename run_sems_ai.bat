@echo off
REM Ejecuta SEMS AI desde el entorno virtual creado por scripts\install_windows.ps1
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo No se encontro el entorno virtual. Ejecute primero scripts\install_windows.ps1
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" run.py
