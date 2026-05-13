# scripts/setup_scheduler.ps1
# Registers a Windows Task Scheduler job that starts the data collector
# every weekday (Mon-Fri) at 09:00 AM local time.
#
# Run ONCE as Administrator:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
#
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "NiftyDataCollector" -Confirm:$false

$ErrorActionPreference = "Stop"

$taskName    = "NiftyDataCollector"
$venvPython  = "d:\trade_on_portal\.venv\Scripts\python.exe"
$script      = "d:\trade_on_portal\collect.py"
$workDir     = "d:\trade_on_portal"
$logFile     = "d:\trade_on_portal\logs\collector_scheduler.log"

# Validate the venv Python exists
if (-not (Test-Path $venvPython)) {
    Write-Error "Venv Python not found at $venvPython. Run: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute   $venvPython `
    -Argument  $script `
    -WorkingDirectory $workDir

# Run Mon–Fri at 09:00 AM
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "09:00AM"

# Kill after 8 hours as a safety net (collect.py self-terminates at 15:35 IST)
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 8) `
    -MultipleInstances   IgnoreNew `
    -StartWhenAvailable  $true `
    -RunOnlyIfNetworkAvailable $false

Register-ScheduledTask `
    -TaskName   $taskName `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -RunLevel   Highest `
    -Force | Out-Null

Write-Output ""
Write-Output "Task '$taskName' registered successfully."
Write-Output ""
Write-Output "Next scheduled run:"
(Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo).NextRunTime
Write-Output ""
Write-Output "To run manually right now:"
Write-Output "  Start-ScheduledTask -TaskName '$taskName'"
Write-Output ""
Write-Output "To remove the task:"
Write-Output "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
