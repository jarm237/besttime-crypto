@echo off
rem run_p8_evaluation.bat: Manual execution wrapper for P8 economic evaluation on Windows.
setlocal enabledelayedexpansion

rem Resolve project root
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."
set "PROJECT_ROOT=%CD%"

rem Ensure venv is available
if not exist ".venv" (
    echo Error: .venv virtual environment not found.
    exit /b 1
)

set "EVIDENCE_DB=%PROJECT_ROOT%\logs\runtime_evidence.sqlite"
set "RESERVATION_DB=%PROJECT_ROOT%\runtime\production\local-production\data\execution\reservations.db"

echo Running P8 Economic Effectiveness Evaluation on Windows...
set "PYTHONPATH=."
".venv\Scripts\python.exe" scripts/p8_economic_report.py ^
    --evidence-db "%EVIDENCE_DB%" ^
    --reservation-db "%RESERVATION_DB%" ^
    --output-dir "%PROJECT_ROOT%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo P8 Evaluation reports generated successfully!
    echo - JSON: p8_economic_effectiveness_report.json
    echo - Markdown: p8_economic_effectiveness_report.md
) else (
    echo Error: P8 Evaluation failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
