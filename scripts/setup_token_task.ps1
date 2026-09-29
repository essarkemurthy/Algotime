# scripts/setup_token_task.ps1
# Register the daily broker-session prompt with Windows Task Scheduler.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_token_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup_token_task.ps1 -At 00:05
#   powershell -ExecutionPolicy Bypass -File scripts\setup_token_task.ps1 -Remove
#
# Runs interactively (-LogonType Interactive) so the console is visible and can
# actually be typed into; a hidden prompt would never be answered. If the
# machine is off at the trigger time, StartWhenAvailable fires it on next logon.

param(
    [string] $At       = "08:00",
    [string] $TaskName = "AlgoTradeDailyToken",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\daily_token.ps1"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

if (-not (Test-Path $script)) { Write-Error "Missing $script"; exit 1 }

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger -Daily -At $At

# Interactive so the window is visible; StartWhenAvailable catches a missed run.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable:$true `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -DontStopOnIdleEnd:$true

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description "Prompt for a fresh Breeze session token (they expire every midnight) and restart the dashboard." | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "  Registered '$TaskName'"
Write-Host "  Runs daily at : $At"
Write-Host "  Next run      : $($info.NextRunTime)"
Write-Host "  Change time   : ...\setup_token_task.ps1 -At 07:30"
Write-Host "  Remove        : ...\setup_token_task.ps1 -Remove"
Write-Host ""
