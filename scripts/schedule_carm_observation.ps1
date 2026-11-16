# PowerShell Management Script for CARM Forward Observation Scheduled Task
# Controls the Windows Scheduled Task on the host machine.

param(
    [string]$TaskName = "CarmShadowObserverHeartbeat",
    [int]$IntervalMinutes = 60,
    [switch]$RunNow,
    [switch]$Status,
    [switch]$Unregister
)

$PythonExe = "C:\Users\admin\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$ScriptPath = "D:\Workspaces\besttime-crypto\scripts\run_carm_forward_observation.py"
$WorkingDirectory = "D:\Workspaces\besttime-crypto"

if ($Status) {
    Write-Host "=== CARM Scheduled Task Status ==="
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Get-ScheduledTask -TaskName $TaskName | Format-List TaskName,State,Actions,Triggers
        Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime,LastTaskResult,NextRunTime,NumberOfMissedRuns
    } else {
        Write-Host "Task '$TaskName' is NOT registered."
    }
    exit 0
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Unregistered scheduled task '$TaskName'."
    exit 0
}

if ($RunNow) {
    Write-Host "Triggering scheduled task '$TaskName' now..."
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime,LastTaskResult,NextRunTime
    exit 0
}

# Default: Register or update scheduled task
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "$ScriptPath --ticks 1" -WorkingDirectory $WorkingDirectory
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 365)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Write-Host "Scheduled task '$TaskName' registered successfully (Interval: $IntervalMinutes minutes)."
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime,LastTaskResult,NextRunTime
