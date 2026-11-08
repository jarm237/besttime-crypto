# scripts/ensure_prospective_raw_epoch_running.ps1
#
# External Supervisor for Prospective Raw Research Epoch R1 Collector
# ====================================================================
# Ensures PROSPECTIVE_RAW_RESEARCH_R1_20261104 collector is running unattended,
# auto-restarts after crashes or system reboot, and supports maintenance pause.
#
# Epistemic & Operational Governance:
# - Strictly external: does not modify frozen collector Python source.
# - Uses O(1) status queries (`run_prospective_raw_epoch.py --status`).
# - Does not start duplicate processes if active or degraded.
# - Does not invoke --force-stop automatically.
# - Does not run full --audit-storage during periodic supervisor cycles.
# - Manages maintenance pause via r1_supervisor.pause.json.
# - Atomically checkpoints bounded r1_supervisor_state.json.

[CmdletBinding(DefaultParameterSetName = "EnsureRunning")]
param(
    [Parameter(ParameterSetName = "EnsureRunning")]
    [switch]$EnsureRunning,

    [Parameter(ParameterSetName = "Pause", Mandatory = $true)]
    [switch]$Pause,

    [Parameter(ParameterSetName = "Pause", Mandatory = $true)]
    [string]$Reason,

    [Parameter(ParameterSetName = "Resume", Mandatory = $true)]
    [switch]$Resume,

    [Parameter(ParameterSetName = "Status", Mandatory = $true)]
    [switch]$Status,

    [Parameter()]
    [string]$StorageDir = "data/prospective_raw_research_r1",

    [Parameter()]
    [string]$RepoRoot = "",

    [Parameter()]
    [string]$PythonExe = "",

    [Parameter()]
    [string]$CollectorScript = "scripts/run_prospective_raw_epoch.py",

    [Parameter()]
    [int]$HeartbeatStaleSeconds = 1200,

    [Parameter()]
    [int]$DegradedEscalationMinutes = 45,

    [Parameter()]
    [int]$StartupWaitSeconds = 15,

    [Parameter()]
    [switch]$JsonOutput
)

$ErrorActionPreference = "Stop"

# 1. Resolve Repository Root
if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

# 2. Resolve Storage Directory
if ([System.IO.Path]::IsPathRooted($StorageDir)) {
    $resolvedStorageDir = [System.IO.Path]::GetFullPath($StorageDir)
} else {
    $resolvedStorageDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $StorageDir))
}

if (-not (Test-Path $resolvedStorageDir)) {
    [System.IO.Directory]::CreateDirectory($resolvedStorageDir) | Out-Null
}

# 3. Resolve Python Executable
$resolvedPythonExe = $PythonExe
if (-not $resolvedPythonExe) {
    try {
        $pyResult = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $pyResult) {
            $resolvedPythonExe = $pyResult.Trim()
        }
    } catch {}
}
if (-not $resolvedPythonExe -or -not (Test-Path $resolvedPythonExe)) {
    # Fallback to python in PATH
    $pyCmd = Get-Command "python" -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $resolvedPythonExe = $pyCmd.Source
    } else {
        $resolvedPythonExe = "py"
    }
}

if ([System.IO.Path]::IsPathRooted($CollectorScript)) {
    $resolvedCollectorScript = [System.IO.Path]::GetFullPath($CollectorScript)
} else {
    $resolvedCollectorScript = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $CollectorScript))
}

# Artifact file paths
$pauseFile = Join-Path $resolvedStorageDir "r1_supervisor.pause.json"
$stateFile = Join-Path $resolvedStorageDir "r1_supervisor_state.json"
$lockFile = Join-Path $resolvedStorageDir "r1_supervisor.lock"
$collectorScript = $resolvedCollectorScript
$stdoutLog = Join-Path $resolvedStorageDir "r1_collector_stdout.log"
$stderrLog = Join-Path $resolvedStorageDir "r1_collector_stderr.log"

function Test-IsProcessAlive([int]$procId) {
    if ($procId -le 0) { return $false }
    try {
        $proc = Get-Process -Id $procId -ErrorAction Stop
        return (-not $proc.HasExited)
    } catch {
        return $false
    }
}

function Get-SupervisorPreviousState {
    if (Test-Path $stateFile) {
        try {
            $raw = Get-Content -Path $stateFile -Raw -Encoding utf8
            return ($raw | ConvertFrom-Json)
        } catch {
            return $null
        }
    }
    return $null
}

function Write-SupervisorAtomicState([hashtable]$stateMap) {
    $prevState = Get-SupervisorPreviousState
    if ($prevState) {
        if (-not $stateMap.ContainsKey("restart_count") -or $null -eq $stateMap["restart_count"]) {
            $stateMap["restart_count"] = if ($prevState.restart_count) { [int]$prevState.restart_count } else { 0 }
        }
        if (-not $stateMap.ContainsKey("last_restart_utc") -or $null -eq $stateMap["last_restart_utc"]) {
            $stateMap["last_restart_utc"] = $prevState.last_restart_utc
        }
    } else {
        if (-not $stateMap.ContainsKey("restart_count") -or $null -eq $stateMap["restart_count"]) {
            $stateMap["restart_count"] = 0
        }
        if (-not $stateMap.ContainsKey("last_restart_utc")) {
            $stateMap["last_restart_utc"] = $null
        }
    }

    $jsonContent = $stateMap | ConvertTo-Json -Depth 5
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $tmpFile = "$stateFile.tmp." + [Guid]::NewGuid().ToString("N")
    [System.IO.File]::WriteAllText($tmpFile, $jsonContent, $utf8NoBom)
    Move-Item -Path $tmpFile -Destination $stateFile -Force
}

function Invoke-CollectorStatus {
    try {
        $procInfo = New-Object System.Diagnostics.ProcessStartInfo
        $procInfo.FileName = $resolvedPythonExe
        $procInfo.Arguments = "-u `"$collectorScript`" --status --storage-dir `"$resolvedStorageDir`""
        $procInfo.WorkingDirectory = $RepoRoot
        $procInfo.RedirectStandardOutput = $true
        $procInfo.RedirectStandardError = $true
        $procInfo.UseShellExecute = $false
        $procInfo.CreateNoWindow = $true

        $proc = [System.Diagnostics.Process]::Start($procInfo)
        $stdOut = $proc.StandardOutput.ReadToEnd()
        $stdErr = $proc.StandardError.ReadToEnd()
        $null = $proc.WaitForExit(10000)

        if ($proc.ExitCode -eq 0 -and $stdOut) {
            return ($stdOut | ConvertFrom-Json)
        }
    } catch {}
    return $null
}

# --- MODE 1: PAUSE ---
if ($Pause) {
    $nowUtc = [DateTime]::UtcNow.ToString("o")
    $pausePayload = @{
        epoch_id = "PROSPECTIVE_RAW_RESEARCH_R1_20261104"
        paused_at_utc = $nowUtc
        reason = $Reason
        paused_by = "supervisor_cli"
    }
    $pauseJson = $pausePayload | ConvertTo-Json -Depth 3
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $tmpPause = "$pauseFile.tmp." + [Guid]::NewGuid().ToString("N")
    [System.IO.File]::WriteAllText($tmpPause, $pauseJson, $utf8NoBom)
    Move-Item -Path $tmpPause -Destination $pauseFile -Force

    $statusObj = Invoke-CollectorStatus
    $curPid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.pid } else { $null }
    $curUuid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.runtime_uuid } else { $null }
    $curOpStatus = if ($statusObj) { $statusObj.operating_status } else { "UNKNOWN" }

    $stateMap = @{
        checked_at_utc = $nowUtc
        supervisor_status = "MAINTENANCE_PAUSED"
        action_taken = "PAUSE_RECORDED"
        collector_pid = $curPid
        collector_runtime_uuid = $curUuid
        collector_operating_status = $curOpStatus
        heartbeat_age_seconds = $null
        last_error = $null
        paused = $true
        pause_reason = $Reason
    }
    Write-SupervisorAtomicState $stateMap

    $resOutput = @{
        status = "OK"
        mode = "PAUSE"
        paused = $true
        reason = $Reason
        state = $stateMap
    }
    $resOutput | ConvertTo-Json -Depth 4
    exit 0
}

# --- MODE 2: RESUME ---
if ($Resume) {
    if (Test-Path $pauseFile) {
        Remove-Item -Path $pauseFile -Force -ErrorAction SilentlyContinue
    }
    # Proceed directly to EnsureRunning
    $EnsureRunning = $true
}

# --- MODE 3: STATUS ---
if ($Status) {
    $isPaused = Test-Path $pauseFile
    $pauseInfo = if ($isPaused) {
        try { Get-Content $pauseFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { $null }
    } else { $null }

    $statusObj = Invoke-CollectorStatus
    $prevState = Get-SupervisorPreviousState

    $nowUtc = [DateTime]::UtcNow.ToString("o")
    $composite = @{
        checked_at_utc = $nowUtc
        supervisor_state = $prevState
        maintenance_paused = $isPaused
        pause_info = $pauseInfo
        collector_live_status = $statusObj
    }
    $composite | ConvertTo-Json -Depth 6
    exit 0
}

# --- MODE 4: ENSURE RUNNING ---
# Attempt lock to prevent overlapping supervisor executions
$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open($lockFile, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
    # Another supervisor instance is running right now
    $statusObj = Invoke-CollectorStatus
    $curPid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.pid } else { $null }
    $curUuid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.runtime_uuid } else { $null }
    $curOpStatus = if ($statusObj) { $statusObj.operating_status } else { "UNKNOWN" }

    $res = @{
        status = "ALREADY_RUNNING"
        message = "Concurrent supervisor instance holds supervisor lock."
        collector_pid = $curPid
        collector_runtime_uuid = $curUuid
        collector_operating_status = $curOpStatus
    }
    if ($JsonOutput) { $res | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR_CONCURRENCY_LOCKED: Another supervisor instance is currently executing." }
    exit 0
}

try {
    $nowUtc = [DateTime]::UtcNow
    $nowIso = $nowUtc.ToString("o")

    # Check maintenance pause
    if (Test-Path $pauseFile) {
        $pauseInfo = try { Get-Content $pauseFile -Raw -Encoding utf8 | ConvertFrom-Json } catch { $null }
        $reason = if ($pauseInfo -and $pauseInfo.reason) { $pauseInfo.reason } else { "MANUAL_MAINTENANCE" }

        $statusObj = Invoke-CollectorStatus
        $curPid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.pid } else { $null }
        $curUuid = if ($statusObj -and $statusObj.heartbeat) { $statusObj.heartbeat.runtime_uuid } else { $null }
        $curOpStatus = if ($statusObj) { $statusObj.operating_status } else { "UNKNOWN" }

        $stateMap = @{
            checked_at_utc = $nowIso
            supervisor_status = "MAINTENANCE_PAUSED"
            action_taken = "SKIPPED_DUE_TO_PAUSE"
            collector_pid = $curPid
            collector_runtime_uuid = $curUuid
            collector_operating_status = $curOpStatus
            heartbeat_age_seconds = $null
            last_error = $null
            paused = $true
            pause_reason = $reason
        }
        Write-SupervisorAtomicState $stateMap
        if ($JsonOutput) { $stateMap | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR: Paused ($reason). No action taken." }
        exit 0
    }

    $statusObj = Invoke-CollectorStatus
    $opStatus = if ($statusObj) { $statusObj.operating_status } else { "UNKNOWN" }
    $lease = if ($statusObj) { $statusObj.lease } else { $null }
    $hb = if ($statusObj) { $statusObj.heartbeat } else { $null }

    $collectorPid = if ($lease -and $lease.pid) { [int]$lease.pid } elseif ($hb -and $hb.pid) { [int]$hb.pid } else { 0 }
    $collectorUuid = if ($lease -and $lease.runtime_uuid) { $lease.runtime_uuid } elseif ($hb -and $hb.runtime_uuid) { $hb.runtime_uuid } else { "" }

    $isAlive = Test-IsProcessAlive $collectorPid

    $heartbeatAgeSec = $null
    if ($hb -and $hb.last_heartbeat_utc) {
        try {
            $hbTime = [DateTime]::Parse($hb.last_heartbeat_utc).ToUniversalTime()
            $heartbeatAgeSec = ($nowUtc - $hbTime).TotalSeconds
        } catch {
            $heartbeatAgeSec = 999999
        }
    }

    # Contract Rule 2: ACTIVE and PID alive and heartbeat fresh -> No action, exit 0
    if ($opStatus -eq "RESEARCH_EPOCH_ACTIVE" -and $isAlive) {
        if ($null -ne $heartbeatAgeSec -and $heartbeatAgeSec -lt $HeartbeatStaleSeconds) {
            $stateMap = @{
                checked_at_utc = $nowIso
                supervisor_status = "HEALTHY_ACTIVE"
                action_taken = "NO_ACTION_ACTIVE"
                collector_pid = $collectorPid
                collector_runtime_uuid = $collectorUuid
                collector_operating_status = $opStatus
                heartbeat_age_seconds = [Math]::Round($heartbeatAgeSec, 2)
                last_error = $null
                paused = $false
                pause_reason = $null
            }
            Write-SupervisorAtomicState $stateMap
            if ($JsonOutput) { $stateMap | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR: Collector PID $collectorPid is ACTIVE and healthy." }
            exit 0
        }
    }

    # Contract Rule 3: DEGRADED but PID alive -> Live but degraded, do not restart loop
    if ($opStatus -eq "RESEARCH_EPOCH_DEGRADED" -and $isAlive) {
        $supervisorStatus = "LIVE_BUT_DEGRADED"
        if ($null -ne $heartbeatAgeSec -and $heartbeatAgeSec -gt ($DegradedEscalationMinutes * 60)) {
            $supervisorStatus = "DEGRADED_ESCALATION_EXCEEDED"
        }
        $stateMap = @{
            checked_at_utc = $nowIso
            supervisor_status = $supervisorStatus
            action_taken = "NO_ACTION_DEGRADED_WAITING_RECOVERY"
            collector_pid = $collectorPid
            collector_runtime_uuid = $collectorUuid
            collector_operating_status = $opStatus
            heartbeat_age_seconds = if ($null -ne $heartbeatAgeSec) { [Math]::Round($heartbeatAgeSec, 2) } else { $null }
            last_error = "Collector degraded. Waiting for internal catchup/recovery."
            paused = $false
            pause_reason = $null
        }
        Write-SupervisorAtomicState $stateMap
        if ($JsonOutput) { $stateMap | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR: Collector PID $collectorPid is DEGRADED. Waiting for internal recovery." }
        exit 0
    }

    # Contract Rule 4: PID alive but heartbeat stale -> Do NOT start second writer, do NOT force stop
    if ($isAlive -and ($null -ne $heartbeatAgeSec -and $heartbeatAgeSec -ge $HeartbeatStaleSeconds)) {
        $stateMap = @{
            checked_at_utc = $nowIso
            supervisor_status = "LIVE_PID_STALE_HEARTBEAT"
            action_taken = "NO_ACTION_AVOID_DUAL_WRITER"
            collector_pid = $collectorPid
            collector_runtime_uuid = $collectorUuid
            collector_operating_status = $opStatus
            heartbeat_age_seconds = [Math]::Round($heartbeatAgeSec, 2)
            last_error = "PID $collectorPid is alive but heartbeat age exceeds threshold ($heartbeatAgeSec s >= $HeartbeatStaleSeconds s)."
            paused = $false
            pause_reason = $null
        }
        Write-SupervisorAtomicState $stateMap
        if ($JsonOutput) { $stateMap | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR: PID $collectorPid alive with stale heartbeat. No second writer spawned." }
        exit 0
    }

    # Contract Rule 5: PID is dead or daemon not running -> Restart exactly one new collector
    Write-Output "SUPERVISOR: Collector PID $collectorPid is not alive (operating_status=$opStatus). Launching new collector daemon..."

    $prevState = Get-SupervisorPreviousState
    $prevRestartCount = if ($prevState -and $prevState.restart_count) { [int]$prevState.restart_count } else { 0 }

    $argList = @(
        "-u",
        $collectorScript,
        "--storage-dir",
        $resolvedStorageDir
    )

    $startParams = @{
        FilePath = $resolvedPythonExe
        ArgumentList = $argList
        WorkingDirectory = $RepoRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdoutLog
        RedirectStandardError = $stderrLog
    }

    $spawnedProcess = Start-Process @startParams -PassThru

    # Wait bounded timeout for initial heartbeat and lease acquisition
    $waitStart = [DateTime]::UtcNow
    $newStatusObj = $null
    $launchedSuccessfully = $false

    while (([DateTime]::UtcNow - $waitStart).TotalSeconds -lt $StartupWaitSeconds) {
        Start-Sleep -Milliseconds 500
        $newStatusObj = Invoke-CollectorStatus
        if ($newStatusObj -and $newStatusObj.operating_status -in @("RESEARCH_EPOCH_ACTIVE", "RESEARCH_EPOCH_DEGRADED")) {
            $launchedSuccessfully = $true
            break
        }
    }

    $finalNewPid = if ($newStatusObj -and $newStatusObj.heartbeat) { $newStatusObj.heartbeat.pid } else { $spawnedProcess.Id }
    $finalNewUuid = if ($newStatusObj -and $newStatusObj.heartbeat) { $newStatusObj.heartbeat.runtime_uuid } else { "" }
    $finalNewOpStatus = if ($newStatusObj) { $newStatusObj.operating_status } else { "LAUNCHED_PENDING_CONFIRMATION" }

    $stateMap = @{
        checked_at_utc = [DateTime]::UtcNow.ToString("o")
        supervisor_status = if ($launchedSuccessfully) { "HEALTHY_ACTIVE" } else { "RESTARTED_PENDING" }
        action_taken = "RESTARTED_COLLECTOR"
        collector_pid = $finalNewPid
        collector_runtime_uuid = $finalNewUuid
        collector_operating_status = $finalNewOpStatus
        heartbeat_age_seconds = 0.0
        restart_count = ($prevRestartCount + 1)
        last_restart_utc = [DateTime]::UtcNow.ToString("o")
        last_error = if (-not $launchedSuccessfully) { "Daemon launched but did not transition to ACTIVE within $StartupWaitSeconds s." } else { $null }
        paused = $false
        pause_reason = $null
    }
    Write-SupervisorAtomicState $stateMap

    if ($JsonOutput) { $stateMap | ConvertTo-Json -Depth 3 } else { Write-Output "SUPERVISOR: Collector restarted successfully with PID $finalNewPid (UUID: $finalNewUuid)." }
    exit 0
}
finally {
    if ($lockStream) {
        $lockStream.Close()
        $lockStream.Dispose()
    }
}
