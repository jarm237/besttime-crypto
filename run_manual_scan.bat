@echo off
chcp 65001 > nul
title Besttime Crypto - Manual Scan (One-Shot)
echo ========================================================================
echo        BESTTIME CRYPTO - MANUAL SCAN (ONE-SHOT 15M ANALYSIS)
echo ========================================================================
python "%~dp0scripts\run_manual_scan.py"
pause
