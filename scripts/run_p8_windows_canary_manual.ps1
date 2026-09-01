# Manual P8 Windows canonical runner helper.
# This script starts/stops/checks the sealed Windows canary runtime only.
# It does not provision epochs, train models, change thresholds, or poll in a loop.

[CmdletBinding()]
param(
    [ValidateSet("start", "status", "stop", "foreground")]
    [string]$Mode = "start",

    [switch]$SkipMongoPreflight
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Worktree = Join-Path $ProjectRoot "runtime\worktrees\windows-canary-20260827-01"
$DeploymentId = "paper-canary-win-20260829-01"
$EpochId = "canary-win-v5-20260829-01"
$ReleaseId = "windows-canary-v1"
$ModelVersion = "windows-v5-filter-1.0.0"
$ArtifactSha256 = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"
$LogDir = Join-Path $Worktree "runtime\paper\$DeploymentId\logs"
$PidFile = Join-Path $LogDir "canonical_runner.pid"
$StdoutPath = Join-Path $LogDir "canonical_runner_stdout.log"
$StderrPath = Join-Path $LogDir "canonical_runner_stderr.log"

function Write-Step([string]$Message) {
    Write-Host "[P8 manual] $Message" -ForegroundColor Cyan
}

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }
}

function Import-DotEnv([string]$Path) {
    Assert-File $Path ".env"
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) {
            continue
        }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) {
            continue
        }
        $name = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
        if ($name -match "^[A-Za-z_][A-Za-z0-9_]*$") {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Set-CanonicalEnvironment() {
    Import-DotEnv $EnvPath
    $env:PYTHONPATH = $Worktree
    $env:PYTHONNOUSERSITE = "1"
    $env:BTC_RUNTIME_ENVIRONMENT = "paper"
    $env:BTC_DEPLOYMENT_ID = $DeploymentId
    $env:BTC_PAPER_RUN_ID = $DeploymentId
    $env:BTC_EVIDENCE_ELIGIBLE = "true"
    $env:AUTO_TRADE_DRY_RUN = "true"
    $env:AUTO_TRADE_BINANCE_TESTNET = "true"
    $env:LIVE_TRADING_ENABLED = "false"
    $env:P8_PHASE = "NATURAL_ECONOMIC_ACCUMULATION"
    $env:P8_EPOCH_ID = $EpochId
    $env:P8_RELEASE_ID = $ReleaseId
    $env:P8_MODEL_VERSION = $ModelVersion
}

function Get-RunnerPid() {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }
    $raw = (Get-Content -LiteralPath $PidFile | Select-Object -First 1).Trim()
    if ($raw -match "^\d+$") {
        return [int]$raw
    }
    return $null
}

function Get-RunnerProcess() {
    $pidValue = Get-RunnerPid
    if ($null -eq $pidValue) {
        return $null
    }
    return Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

function Invoke-MongoPreflight() {
    if ($SkipMongoPreflight) {
        Write-Step "Mongo preflight skipped by flag."
        return
    }
    $code = @'
import os
from pymongo import MongoClient
import certifi

uri = os.environ.get("MONGODB_URI")
if not uri:
    print("MONGODB_PREFLIGHT=FAIL_MISSING_URI")
    raise SystemExit(2)

kwargs = {
    "serverSelectionTimeoutMS": 8000,
    "connectTimeoutMS": 8000,
    "socketTimeoutMS": 8000,
}
if uri.startswith("mongodb+srv"):
    kwargs.update({"tls": True, "tlsCAFile": certifi.where()})

client = None
try:
    client = MongoClient(uri, **kwargs)
    client.admin.command("ping")
    db_name = uri.rsplit("/", 1)[-1].split("?", 1)[0]
    db = client.get_default_database() if db_name else client["besttime_crypto"]
    col = db["_runtime_preflight"]
    doc = {"_id": "p8_windows_canary_manual", "purpose": "manual-runner-preflight"}
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    found = col.count_documents({"_id": doc["_id"]})
    col.delete_one({"_id": doc["_id"]})
    if found != 1:
        print("MONGODB_PREFLIGHT=FAIL_WRITE_VERIFY")
        raise SystemExit(2)
    print("MONGODB_PREFLIGHT=PASS_READ_WRITE")
except Exception as exc:
    details = getattr(exc, "details", None)
    errmsg = details.get("errmsg") if isinstance(details, dict) else str(exc).splitlines()[0]
    if len(errmsg) > 360:
        errmsg = errmsg[:360] + "..."
    print(f"MONGODB_PREFLIGHT=FAIL type={type(exc).__name__} code={getattr(exc, 'code', None)} errmsg={errmsg}")
    raise SystemExit(2)
finally:
    if client:
        client.close()
'@
    $code | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "Mongo preflight failed; runner not started."
    }
}

function Assert-ActiveEpoch() {
    $code = @'
import json
import os
import sqlite3
import subprocess
from pathlib import Path

worktree = Path(os.environ["PYTHONPATH"])
deployment_id = os.environ["BTC_DEPLOYMENT_ID"]
epoch_id = os.environ["P8_EPOCH_ID"]
model_version = os.environ["P8_MODEL_VERSION"]
artifact_sha256 = os.environ["P8_EXPECTED_ARTIFACT_SHA256"]
db_path = worktree / "runtime" / "paper" / deployment_id / "logs" / "global_evidence_index.sqlite"
if not db_path.exists():
    print(f"EPOCH_PREFLIGHT=FAIL_MISSING_INDEX path={db_path}")
    raise SystemExit(2)

head = subprocess.check_output(["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True).strip()
con = sqlite3.connect(db_path, timeout=2)
try:
    rows = con.execute(
        "select epoch_id,deployment_id,status,model_version,artifact_sha256,code_commit_sha,paper_run_id "
        "from evidence_epochs where status='ACTIVE'"
    ).fetchall()
finally:
    con.close()

if len(rows) != 1:
    print(f"EPOCH_PREFLIGHT=FAIL_ACTIVE_COUNT count={len(rows)}")
    raise SystemExit(2)

row = rows[0]
expected = (epoch_id, deployment_id, "ACTIVE", model_version, artifact_sha256, head, deployment_id)
if tuple(str(x) for x in row) != tuple(str(x) for x in expected):
    print("EPOCH_PREFLIGHT=FAIL_IDENTITY")
    print(json.dumps({"actual": row, "expected": expected}, default=str))
    raise SystemExit(2)

print("EPOCH_PREFLIGHT=PASS_ACTIVE_CANONICAL")
'@
    $env:P8_EXPECTED_ARTIFACT_SHA256 = $ArtifactSha256
    $code | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "Canonical epoch preflight failed; runner not started."
    }
}

function Show-RunnerStatus() {
    Write-Host "P8 Windows canonical runner"
    Write-Host "Epoch:      $EpochId"
    Write-Host "Deployment: $DeploymentId"
    Write-Host "Worktree:   $Worktree"
    Write-Host "Logs:       $LogDir"
    $pidValue = Get-RunnerPid
    $process = Get-RunnerProcess
    Write-Host "PID file:   $pidValue"
    Write-Host "Alive:      $([bool]$process)"
    if ($process) {
        Write-Host "Name:       $($process.ProcessName)"
        Write-Host "Started:    $($process.StartTime)"
        Write-Host "Memory MB:  $([Math]::Round($process.WorkingSet64 / 1MB, 1))"
    }
    if (Test-Path -LiteralPath $StderrPath) {
        Write-Host ""
        Write-Host "Recent suspicious stderr lines:"
        Select-String -Path $StderrPath -Pattern "Traceback|ERROR|WARNING|mismatch|bad auth|artifact_missing|model_artifact|missing_lineage" -CaseSensitive:$false |
            Select-Object -Last 30 |
            ForEach-Object { Write-Host ($_.LineNumber.ToString() + ": " + $_.Line) }
    }
}

Assert-File $PythonExe "Python executable"
Assert-File $Worktree "Windows canary worktree"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

switch ($Mode) {
    "status" {
        Show-RunnerStatus
        exit 0
    }
    "stop" {
        $pidValue = Get-RunnerPid
        $process = Get-RunnerProcess
        if (-not $process) {
            Write-Step "Runner is not running."
            exit 0
        }
        Stop-Process -Id $pidValue -Force
        Write-Step "Stopped runner PID $pidValue."
        exit 0
    }
    "foreground" {
        $existing = Get-RunnerProcess
        if ($existing) {
            throw "Runner already appears alive. Use -Mode status or -Mode stop first."
        }
        Set-CanonicalEnvironment
        Invoke-MongoPreflight
        Assert-ActiveEpoch
        Set-Location -LiteralPath $Worktree
        Write-Step "Starting foreground runner. Press Ctrl+C to stop."
        & $PythonExe main.py
        exit $LASTEXITCODE
    }
    "start" {
        $existing = Get-RunnerProcess
        if ($existing) {
            Write-Step "Runner already alive with PID $($existing.Id)."
            Show-RunnerStatus
            exit 0
        }
        Set-CanonicalEnvironment
        Invoke-MongoPreflight
        Assert-ActiveEpoch
        $process = Start-Process -FilePath $PythonExe `
            -ArgumentList @("main.py") `
            -WorkingDirectory $Worktree `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -PassThru `
            -WindowStyle Hidden
        Set-Content -LiteralPath $PidFile -Value $process.Id
        Write-Step "Started runner PID $($process.Id)."
        Write-Host "stdout: $StdoutPath"
        Write-Host "stderr: $StderrPath"
        exit 0
    }
}
