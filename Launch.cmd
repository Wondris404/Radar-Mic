@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run powershell -ExecutionPolicy Bypass -File scripts\install.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m radar_mic.app %*
