# scripts/unregister_r1_supervisor_task.ps1
#
# Unregisters Windows Scheduled Task for R1 Collector Supervisor
# ==============================================================

param(
    [string]$TaskName = "BesttimeCrypto-R1-DemoCollector",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$supervisorScript = Join-Path $RepoRoot "scripts\ensure_prospective_raw_epoch_running.ps1"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $actionArgs = $existing.Actions | Select-Object -ExpandProperty Arguments -ErrorAction SilentlyContinue
    $matchesRepo = ($actionArgs -and $actionArgs.Contains($supervisorScript))
    if (-not $matchesRepo) {
        throw "SECURITY VIOLATION: Scheduled task '$TaskName' exists but does NOT belong to this repository (arguments: $actionArgs). Refusing to unregister unknown task."
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "SUCCESS: Scheduled Task '$TaskName' unregistered."
} else {
    Write-Output "Task '$TaskName' does not exist."
}

