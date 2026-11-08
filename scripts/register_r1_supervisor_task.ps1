# scripts/register_r1_supervisor_task.ps1
#
# Registers Windows Scheduled Task for R1 Collector Supervisor
# ============================================================
# Task Name: BesttimeCrypto-R1-DemoCollector
# Triggers: At logon + Repetition every 5 minutes
# Action: powershell.exe -File ensure_prospective_raw_epoch_running.ps1 -EnsureRunning
# Settings: IgnoreNew, 5m timeout, battery support, start when available

param(
    [string]$TaskName = "BesttimeCrypto-R1-DemoCollector",
    [string]$RepoRoot = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$supervisorScript = Join-Path $RepoRoot "scripts\ensure_prospective_raw_epoch_running.ps1"
if (-not (Test-Path $supervisorScript)) {
    throw "Supervisor script not found at: $supervisorScript"
}

# 1. Query existing task
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $actionArgs = $existing.Actions | Select-Object -ExpandProperty Arguments -ErrorAction SilentlyContinue
    $matchesRepo = ($actionArgs -and $actionArgs.Contains($supervisorScript))
    if (-not $matchesRepo) {
        throw "SECURITY VIOLATION: Scheduled task '$TaskName' already exists but does NOT belong to this repository (arguments: $actionArgs). Refusing to overwrite unknown task."
    }
    Write-Output "Updating existing scheduled task '$TaskName' for this repository..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 2. Define Triggers:
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)

# 3. Define Action:
$psExe = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
$psArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$supervisorScript`" -EnsureRunning"
$action = New-ScheduledTaskAction -Execute $psExe -Argument $psArguments -WorkingDirectory $RepoRoot

# 4. Define Settings:
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# 5. Register Task
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($t1, $t2) `
    -Settings $settings `
    -Description "Besttime Crypto Prospective R1 Demo Collector Supervisor (Logon + 5m Repetition)" | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName
Write-Output "SUCCESS: Scheduled Task '$TaskName' registered successfully (State: $($registered.State))."

