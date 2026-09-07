# PowerShell script for running Besttime Crypto Manual Runner
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "       BESTTIME CRYPTO - MANUAL FOREGROUND RUNNER" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

$ScriptPath = Join-Path $PSScriptRoot "scripts\run_manual_runner.py"
python $ScriptPath
