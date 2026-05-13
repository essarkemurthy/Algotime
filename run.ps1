# run.ps1 — Activate venv and start the engine
# Usage: .\run.ps1
#        .\run.ps1 --strategy iron_condor --lots 2

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

& "$scriptDir\.venv\Scripts\Activate.ps1"
python "$scriptDir\main.py" @args
