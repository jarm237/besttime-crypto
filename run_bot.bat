@echo off
rem run_bot.bat: Batch helper script to execute the besttime-crypto trading bot.
setlocal enabledelayedexpansion

rem Resolve project root
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

rem Ensure venv is available
if not exist ".venv" (
    echo Error: .venv virtual environment not found.
    exit /b 1
)

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Error: python.exe not found in .venv\Scripts
    exit /b 1
)

echo Starting Trading Bot...
"%PYTHON_EXE%" main.py %*

if %ERRORLEVEL% neq 0 (
    echo Trading Bot exited with error code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
