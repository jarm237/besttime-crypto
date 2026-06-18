param(
  [string]$Time = "02:00",
  [string]$Schedule = "DAILY",
  [string]$TaskName = "PeriodicRecalibration"
)

$WorkDir = "D:\Workspaces\Vọc vạch"
$Python = "python"
$Log = Join-Path $WorkDir "logs\\periodic_recalibration_task.log"

# Build action: run via cmd to ensure working directory change
$cmd = 'cd /d "' + $WorkDir + '" && ' + $Python + ' scripts/periodic_recalibration.py >> "' + $Log + '" 2>&1'
$Action = 'cmd /c "' + $cmd + '"'

Write-Output "Registering scheduled task '$TaskName' to run $Schedule at $Time using Register-ScheduledTask"

# Parse hour/minute from $Time
$parts = $Time -split ':'
if ($parts.Length -ne 2) {
  Write-Output "Invalid time format. Use HH:MM"
  exit 2
}
$hour = [int]$parts[0]
$min = [int]$parts[1]

# Build action: run a PowerShell command that sets location then runs the python script
$psCmd = "Set-Location -Path '$WorkDir'; $Python scripts/periodic_recalibration.py >> '$Log' 2>&1"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -Command \"$psCmd\""

if ($Schedule -eq 'DAILY') {
  $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $hour -Minute $min -Second 0)
} else {
  # fallback: daily
  $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour $hour -Minute $min -Second 0)
}

try {
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -RunLevel Highest -Force
  Write-Output "Scheduled task registered: $TaskName"
} catch {
  Write-Output "Register-ScheduledTask failed: $_"
  exit 1
}
