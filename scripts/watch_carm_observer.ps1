<#
.SYNOPSIS
    Manual Foreground Observer Monitor for CARM Shadow Observer.

.DESCRIPTION
    Runs the CARM Read-Only Prospective Shadow Observer in a dedicated foreground terminal loop.
    NO background jobs, NO daemons, NO Windows Scheduled Tasks.
    State and ledger are monotonically persisted on disk. Pressing Ctrl+C halts the loop
    without resetting portfolio state or corrupting logs.

.PARAMETER IntervalSeconds
    Interval in seconds between observation ticks (default: 60).

.PARAMETER Once
    Executes exactly one observation tick and exits immediately.

.PARAMETER Probe
    Executes in isolated probe sandbox with --probe-rebalance flag (protects canonical epoch).

.PARAMETER PythonExe
    Explicit path to python executable. Auto-detected if omitted.
#>

[CmdletBinding()]
param(
    [int]$IntervalSeconds = 60,
    [switch]$Once,
    [switch]$Probe,
    [string]$PythonExe = ""
)

# Auto-detect Python executable
if (-not $PythonExe) {
    $candidates = @(
        "C:\Users\admin\AppData\Local\Python\pythoncore-3.14-64\python.exe",
        (Get-Command python -ErrorAction SilentlyContinue).Source,
        (Get-Command py -ErrorAction SilentlyContinue).Source
    )
    foreach ($cand in $candidates) {
        if ($cand -and (Test-Path $cand)) {
            $PythonExe = $cand
            break
        }
    }
}

if (-not $PythonExe -or -not (Test-Path $PythonExe)) {
    Write-Error "Python executable not found. Please specify -PythonExe <path>."
    exit 1
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$RunnerScript = Join-Path $RepoRoot "scripts\run_carm_forward_observation.py"

if (-not (Test-Path $RunnerScript)) {
    Write-Error "Runner script not found at $RunnerScript"
    exit 1
}

$EpochDir = if ($Probe) {
    Join-Path $RepoRoot "logs\carm_observer\probe_sandbox"
} else {
    Join-Path $RepoRoot "logs\carm_observer\canonical_epoch"
}
$SnapshotPath = Join-Path $EpochDir "first_forward_evidence_snapshot.json"
$StatePath = Join-Path $EpochDir "carm_state.json"
$LogPath = Join-Path $EpochDir "watcher.log"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "    CARM SHADOW OBSERVER -- MANUAL FOREGROUND MONITOR       " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Mode:             MANUAL FOREGROUND ONLY (No background/cron)" -ForegroundColor White
Write-Host "  Epoch Target:     $(if ($Probe) { 'PROBE_SANDBOX (Isolated)' } else { 'CANONICAL_EPOCH (EPOCH_20261116_02)' })" -ForegroundColor White
Write-Host "  Interval:         $IntervalSeconds seconds (Once: $Once)" -ForegroundColor White
Write-Host "  Log File:         $LogPath" -ForegroundColor White
Write-Host "  Safety:           REAL_TRADING = False (Zero live orders)" -ForegroundColor Green
Write-Host "  Control:          Press Ctrl+C to halt safely at any time" -ForegroundColor Magenta
Write-Host "============================================================`n" -ForegroundColor Cyan

$sessionStart = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogPath -Value "[$sessionStart] [START] Observer session initialized (Interval: ${IntervalSeconds}s, Once: $Once, Target: $EpochDir)" -Encoding ASCII -ErrorAction SilentlyContinue

$tickCount = 0

while ($true) {
    $tickCount++
    $nowLocal = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$nowLocal] --- Tick $tickCount Initiating ---" -ForegroundColor Cyan

    $argsList = @($RunnerScript, "--ticks", "1")
    if ($Probe) {
        $argsList += "--probe-rebalance"
    }

    # Execute single tick in foreground
    & $PythonExe $argsList
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Host "`n[API/DATA ERROR] Runner exited with code $exitCode. Market data or API issue." -ForegroundColor Red
        Add-Content -Path $LogPath -Value "[$nowLocal] [ERROR] Tick $tickCount exited with code $exitCode" -Encoding ASCII -ErrorAction SilentlyContinue
    } else {
        # Parse and display real-time telemetry from evidence snapshot
        if (Test-Path $SnapshotPath) {
            try {
                $rawJson = Get-Content $SnapshotPath -Raw -Encoding UTF8
                $snap = ConvertFrom-Json $rawJson

                Write-Host "`n>>> TELEMETRY SNAPSHOT (Epoch: $($snap.epoch_id)) <<<" -ForegroundColor Green
                Write-Host ("  Timestamp (UTC):    {0}" -f $snap.session_end_utc)
                Write-Host ("  Buffer Bars:        {0} closed 1h klines" -f $snap.hourly_bars_in_buffer)
                Write-Host ("  Forward Obvs:       {0}" -f $snap.counters.authentic_forward_observations)
                Write-Host ("  Scheduled Rebal:    {0}" -f $snap.counters.scheduled_weekly_rebalances)
                Write-Host ("  Inception Rebal:    {0}" -f $snap.counters.inception_rebalances)
                Write-Host ("  CARM Equity:        `${0:N2} ({1:P2})" -f $snap.latest_portfolio_equity.carm_equity_usd, ($snap.latest_portfolio_equity.carm_net_return_pct / 100.0)) -ForegroundColor Yellow
                Write-Host ("  BTC Buy&Hold:       `${0:N2} ({1:P2})" -f $snap.latest_portfolio_equity.btc_bh_equity_usd, ($snap.latest_portfolio_equity.btc_bh_net_return_pct / 100.0)) -ForegroundColor Gray
                Write-Host ("  Cash Benchmark:     `${0:N2}" -f $snap.latest_portfolio_equity.cash_equity_usd) -ForegroundColor Gray

                # Log tick summary to file
                $logLine = ("[{0}] [TICK] #{1} | Obvs: {2} | Bars: {3} | CARM: `${4:N2} ({5:P2}) | BTC: `${6:N2} ({7:P2}) | Cash: `${8:N2}" -f `
                    $nowLocal, $tickCount, $snap.counters.authentic_forward_observations, $snap.hourly_bars_in_buffer, `
                    $snap.latest_portfolio_equity.carm_equity_usd, ($snap.latest_portfolio_equity.carm_net_return_pct / 100.0), `
                    $snap.latest_portfolio_equity.btc_bh_equity_usd, ($snap.latest_portfolio_equity.btc_bh_net_return_pct / 100.0), `
                    $snap.latest_portfolio_equity.cash_equity_usd)
                Add-Content -Path $LogPath -Value $logLine -Encoding ASCII -ErrorAction SilentlyContinue

                # Universe Spot Prices
                if ($snap.latest_prices) {
                    $priceStrings = @()
                    foreach ($prop in $snap.latest_prices.PSObject.Properties) {
                        $priceStrings += ("{0}=`${1:N2}" -f $prop.Name, [double]$prop.Value)
                    }
                    Write-Host ("  Market Prices:      {0}" -f ($priceStrings -join ", ")) -ForegroundColor DarkCyan
                }
            } catch {
                Write-Warning "Could not parse snapshot: $_"
            }
        }
    }

    if ($Once) {
        Write-Host "`n[COMPLETED] Single tick (-Once) completed successfully." -ForegroundColor Green
        break
    }

    Write-Host "`n[WAITING] Next tick in $IntervalSeconds seconds... (Press Ctrl+C to halt)" -ForegroundColor DarkGray
    Start-Sleep -Seconds $IntervalSeconds
}
