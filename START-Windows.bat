@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Velosyntech Auto-Poster
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python nu e instalat.
  echo  Instaleaza-l de pe https://www.python.org/downloads/
  echo  IMPORTANT: bifeaza "Add python.exe to PATH" la instalare, apoi porneste din nou.
  start https://www.python.org/downloads/
  pause
  exit /b
)

if not exist ".venv\Scripts\python.exe" (
  echo Prima pornire: instalez ce trebuie, dureaza 1-2 minute...
  python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt

".venv\Scripts\python.exe" -m autoposter start
pause
