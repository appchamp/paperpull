@echo off
REM Double-clickable Windows launcher for PG&E Statement Intelligence Dashboard
cd /d "%~dp0"

echo ⚡ Launching PG&E Statement Intelligence Dashboard...

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

"%PYTHON%" pge_intel.py
pause
