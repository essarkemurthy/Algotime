#!/usr/bin/env python3
"""
scripts/run_batch2.py — Second-batch downloader.

Uses remaining ~1966 Breeze API calls from today's session to:
  1. Extend ALL symbols' daily data to 2 years (backward gap-fill)
  2. Add 1-minute data for all Nifty 50 stocks
  3. Add 5-minute + 1-minute data for all Nifty Next 50 stocks

Run once per day after the main bulk_download.py completes.
Safe to interrupt and re-run (gap detection + progress file).

Usage:
  python scripts/run_batch2.py
  python scripts/run_batch2.py --stop-at 23:50
"""

import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "scripts" / "bulk_download.py")
PYTHON = sys.executable

def run(label, args, max_calls):
    print(f"\n{'='*60}")
    print(f"BATCH: {label}  (cap: {max_calls} calls)")
    print(f"{'='*60}")
    cmd = [PYTHON, SCRIPT] + args + [f"--max-calls={max_calls}"]
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"[WARN] {label} exited with code {result.returncode} — continuing")

stop_at = "--stop-at=23:50"
for arg in sys.argv[1:]:
    if arg.startswith("--stop-at"):
        stop_at = arg

# Phase 1: Extend ALL daily data to 2 years (backward gap-fill for already-present symbols)
run(
    "All symbols — daily 2 years (backward gap-fill)",
    ["--universe", "all", "--intervals", "1day", "--days", "730", stop_at],
    max_calls=260,
)

# Phase 2: 1-minute data for all Nifty 50 stocks (new interval — not in progress file)
run(
    "Nifty 50 — 1-minute, 1 year",
    ["--universe", "nifty50", "--intervals", "1minute", stop_at],
    max_calls=800,
)

# Phase 3: 5-minute + 1-minute data for all Nifty Next 50 stocks
run(
    "Nifty Next 50 — 5-minute + 1-minute, 1 year",
    ["--universe", "nextnifty50", "--intervals", "5minute", "1minute", stop_at],
    max_calls=900,
)

print("\nAll batches complete.")
