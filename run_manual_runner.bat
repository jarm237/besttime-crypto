@echo off
chcp 65001 > nul
title Besttime Crypto - Manual Runner
echo ========================================================================
echo        BESTTIME CRYPTO - MANUAL FOREGROUND RUNNER
echo ========================================================================
python "%~dp0scripts\run_manual_runner.py"
pause
