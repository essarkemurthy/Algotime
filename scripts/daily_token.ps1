# scripts/daily_token.ps1
# Daily broker-session refresh. Breeze tokens die every midnight, so this asks
# for a fresh one, and restarts the dashboard once a valid token is stored.
#
# Registered as a scheduled task by scripts/setup_token_task.ps1. Runs in a
# visible console (an invisible prompt would never be answered) and stays open
# until you respond, so it is still waiting whenever you reach the machine.
#
#   powershell -ExecutionPolicy Bypass -File scripts\daily_token.ps1
#   -NoRestart   validate + save only, leave the running app alone

param(
    [switch] $NoRestart
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $repo ".venv\Scripts\python.exe"
Set-Location $repo

Write-Host ""
Write-Host "  ============================================================"
Write-Host "   Daily broker session refresh - $(Get-Date -Format 'ddd dd MMM yyyy HH:mm')"
Write-Host "  ============================================================"

if (-not (Test-Path $py)) {
    Write-Host "  [ERROR] venv python missing at $py"
    Read-Host "  Press Enter to close"
    exit 1
}

# Preflight validates the saved token and only prompts if it is actually dead,
# reusing the api key/secret already stored in .env / data/setup.json.
& $py (Join-Path $repo "scripts\preflight_token.py")
$rc = $LASTEXITCODE

if ($rc -ne 0) {
    Write-Host ""
    Write-Host "  No valid session stored. The dashboard will stay OFFLINE until"
    Write-Host "  a token is provided - rerun this window, or use the desktop shortcut."
    Read-Host "  Press Enter to close"
    exit 1
}

if ($NoRestart) {
    Write-Host "  Token saved. -NoRestart given, leaving the app as-is."
    exit 0
}

# Restart so the new token is actually picked up. Skipped when nothing is
# listening - the launcher will read the fresh token on next start anyway.
$listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Host ""
    Write-Host "  Restarting the dashboard to pick up the new token..."
    & powershell -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $repo "scripts\restart_app.ps1") -Force
} else {
    Write-Host "  Dashboard is not running - start it from the desktop shortcut."
}

Write-Host ""
Write-Host "  Done."
Start-Sleep -Seconds 5
