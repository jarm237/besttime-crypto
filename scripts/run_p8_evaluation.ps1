<# 
run_p8_evaluation.ps1

Manual one-shot runner for P8 Natural Economic Accumulation evaluation.

This script is intentionally passive:
- no background process
- no scheduler
- no polling loop
- no model, threshold, universe, routing, risk, or execution-policy changes

Run manually at the authorized checkpoint:
  powershell -ExecutionPolicy Bypass -File scripts/run_p8_evaluation.ps1
#>

[CmdletBinding()]
param(
    [string]$EvidenceDb,
    [string]$ReservationDb,
    [string]$OutputDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Resolve script directory and project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Get-Item (Join-Path $ScriptDir "..")
Set-Location -Path $ProjectRoot.FullName

if (-not $EvidenceDb) {
    $EvidenceDb = Join-Path $ProjectRoot.FullName "logs\runtime_evidence.sqlite"
}
if (-not $ReservationDb) {
    $ReservationDb = Join-Path $ProjectRoot.FullName "runtime\production\local-production\data\execution\reservations.db"
}
if (-not $OutputDir) {
    $OutputDir = $ProjectRoot.FullName
}

# Ensure venv is available
$VenvPath = Join-Path $ProjectRoot.FullName ".venv"
if (-not (Test-Path $VenvPath)) {
    Write-Error "Error: .venv virtual environment not found in $($ProjectRoot.FullName)"
    exit 1
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Error: python.exe not found in $VenvPath\Scripts"
    exit 1
}

$EvidencePath = [System.IO.Path]::GetFullPath($EvidenceDb)
$ReservationPath = [System.IO.Path]::GetFullPath($ReservationDb)
$OutputPath = [System.IO.Path]::GetFullPath($OutputDir)

$EvidenceParent = Split-Path -Parent $EvidencePath
$EvidenceLeaf = Split-Path -Leaf $EvidencePath
$EvidenceStem = [System.IO.Path]::GetFileNameWithoutExtension($EvidenceLeaf)
$EvidenceExt = [System.IO.Path]::GetExtension($EvidenceLeaf)
$PartitionPattern = "$($EvidenceStem)_????-??-??$EvidenceExt"
$PartitionFiles = @()
if (Test-Path $EvidenceParent) {
    $PartitionFiles = @(Get-ChildItem -Path $EvidenceParent -Filter $PartitionPattern -File)
}

if ((-not (Test-Path $EvidencePath)) -and ($PartitionFiles.Count -eq 0)) {
    Write-Error "Error: evidence DB not found at $EvidencePath and no partitions matched $PartitionPattern"
    exit 1
}

if (-not (Test-Path $ReservationPath)) {
    Write-Error "Error: reservation DB not found at $ReservationPath"
    exit 1
}

if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath | Out-Null
}

Write-Host "P8 manual evaluation runner" -ForegroundColor Cyan
Write-Host "Phase: NATURAL_ECONOMIC_ACCUMULATION"
Write-Host "State: ACCUMULATING"
Write-Host "Primary population: CURRENT_CANARY"
Write-Host "Synthetic trades: NOT_AUTHORIZED"
Write-Host "Active P8 engineering: NONE"
Write-Host "Execution mode: one-shot manual evaluation"
Write-Host "Evidence DB: $EvidencePath"
if ($PartitionFiles.Count -gt 0) {
    Write-Host "Evidence partitions: $($PartitionFiles.Count) matched $PartitionPattern"
}
Write-Host "Reservation DB: $ReservationPath"
Write-Host "Output dir: $OutputPath"
Write-Host ""

# Set PYTHONPATH to root directory
$env:PYTHONPATH = $ProjectRoot.FullName

# Run evaluation script with explicit inputs and outputs
& $PythonExe scripts/p8_economic_report.py `
    --evidence-db $EvidencePath `
    --reservation-db $ReservationPath `
    --output-dir $OutputPath

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nP8 Evaluation reports generated successfully!" -ForegroundColor Green
    Write-Host "- JSON: $(Join-Path $OutputPath 'p8_economic_effectiveness_report.json')" -ForegroundColor Green
    Write-Host "- Markdown: $(Join-Path $OutputPath 'p8_economic_effectiveness_report.md')" -ForegroundColor Green
} else {
    Write-Error "Error: P8 Evaluation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
