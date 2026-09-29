# scripts/restart_app.ps1
# Restart the dashboard so it picks up a refreshed BREEZE_SESSION_TOKEN, then
# re-arm the paper algo engines (trade_intraday / trade_options reset to false
# on every start, so they must be turned back on explicitly).
#
# Intended to run when the market is CLOSED and paper positions are flat —
# a mid-session restart drops open in-memory positions without recording exits.
#
#   powershell -ExecutionPolicy Bypass -File scripts\restart_app.ps1
#
# -TaskName  self-unregister that scheduled task once the restart succeeds.

param(
    [int]    $Port        = 8000,
    [string] $TaskName    = "",
    [switch] $Interactive,   # allow the token preflight to prompt
    [switch] $Force          # restart even if the session is dead
)

$ErrorActionPreference = "Stop"
$repo   = Split-Path -Parent $PSScriptRoot
$py     = Join-Path $repo ".venv\Scripts\python.exe"
$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory $logDir | Out-Null }
$log    = Join-Path $logDir "restart_app.log"
$appLog = Join-Path $logDir ("app_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Say($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

Say "=== restart requested ==="

if (-not (Test-Path $py)) { Say "ERROR venv python missing at $py"; exit 1 }

# --- 1. Warn if positions are still open -------------------------------------
try {
    $snap = Invoke-RestMethod "http://localhost:$Port/api/algo/paper" -TimeoutSec 8
    if ($snap.open_count -gt 0) {
        Say ("WARNING {0} paper positions still open - they will be lost" -f $snap.open_count)
    } else {
        Say "no open paper positions - safe to restart"
    }
} catch { Say "app not responding (already down?)" }

# --- 1b. Broker session -------------------------------------------------------
# Validate before tearing the old instance down: restarting onto a dead token
# just trades a working-but-stale app for a disconnected one.
$pre = Join-Path $repo "scripts\preflight_token.py"
if (Test-Path $pre) {
    if ($Interactive) {
        & $py $pre                       # may prompt for a fresh token
    } else {
        & $py $pre "--check" | Out-Null  # unattended: never block on input
    }
    if ($LASTEXITCODE -ne 0) {
        Say "WARNING broker session not active - app will start OFFLINE"
        if (-not $Force) {
            Say "aborting; pass -Force to restart anyway, or -Interactive to be prompted"
            exit 1
        }
    } else {
        Say "broker session validated"
    }
}

# --- 2. Stop whatever holds the port -----------------------------------------
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
    Say "stopping PID $procId on port $Port"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
for ($i = 0; $i -lt 20; $i++) {
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Say "ERROR port $Port still busy"; exit 1
}
Say "port $Port free"

# --- 3. Start detached, so it outlives this script ---------------------------
Say "starting app.py (log -> $appLog)"
Start-Process -FilePath $py -ArgumentList "app.py" -WorkingDirectory $repo `
              -WindowStyle Hidden -RedirectStandardOutput $appLog `
              -RedirectStandardError ($appLog -replace '\.log$', '.err.log')

# --- 4. Wait for the Breeze session to come up -------------------------------
$connected = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    try {
        $st = Invoke-RestMethod "http://localhost:$Port/api/status" -TimeoutSec 3
        if ($st.connected) { $connected = $true; break }
    } catch { }
}
if (-not $connected) {
    Say "ERROR app did not connect to Breeze - token may be stale. See $appLog"
    exit 1
}
Say "connected to Breeze"

# --- 5. Re-arm the paper algo ------------------------------------------------
try {
    $body = '{"trade_intraday": true, "trade_options": true}'
    $r = Invoke-RestMethod "http://localhost:$Port/api/algo/paper/config" -Method Post `
                           -ContentType "application/json" -Body $body -TimeoutSec 15
    Say ("algo re-armed: intraday={0} options={1}" -f $r.config.trade_intraday, $r.config.trade_options)
} catch {
    Say "ERROR could not re-arm the paper algo: $_"
    exit 1
}

Say "=== restart complete ==="

# --- 6. One-shot task cleans itself up ---------------------------------------
if ($TaskName) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Say "removed scheduled task '$TaskName'"
    } catch { Say "could not remove task '$TaskName': $_" }
}
