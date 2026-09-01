# run_bot.ps1: PowerShell helper script to execute the besttime-crypto trading bot.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Resolve project root directory
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ProjectRoot

# Verify virtual environment exists
$VenvPath = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $VenvPath)) {
    Write-Error "Error: .venv virtual environment not found. Please create it or run setup first."
    exit 1
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Error: python.exe not found in $VenvPath\Scripts"
    exit 1
}

Write-Host "Starting Trading Bot in the virtual environment..." -ForegroundColor Cyan

# Execute main.py, forwarding all command-line arguments
& $PythonExe main.py @args

if ($LASTEXITCODE -ne 0) {
    Write-Error "Trading Bot exited with error code $LASTEXITCODE"
    exit $LASTEXITCODE
}
