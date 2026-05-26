#!/usr/bin/env python3
"""Comprehensive gap analysis of candles table."""
import os, sys
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
conn = psycopg2.connect(os.environ["DB_URL"])
cur = conn.cursor()

print("=" * 80)
print("GAP ANALYSIS REPORT")
print("=" * 80)

# ── 1. Overall summary ────────────────────────────────────────────────────────
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT interval),
           MIN(ts)::date, MAX(ts)::date
    FROM candles
""")
total, syms, ivs, mn, mx = cur.fetchone()
print(f"\nTotal candles : {total:,}")
print(f"Symbols       : {syms}")
print(f"Intervals     : {ivs}")
print(f"Date range    : {mn} -> {mx}")

# ── 2. Which symbols are missing which intervals ──────────────────────────────
print("\n" + "=" * 80)
print("MISSING INTERVALS PER SYMBOL")
print("=" * 80)
cur.execute("""
    SELECT symbol, array_agg(DISTINCT interval ORDER BY interval) AS has_ivs
    FROM candles
    GROUP BY symbol
    ORDER BY symbol
""")
rows = cur.fetchall()
expected = {"1d", "1m", "30m", "5m"}
missing_any = []
for sym, has in rows:
    has_set = set(has)
    missing = expected - has_set
    if missing:
        missing_any.append((sym, sorted(missing), sorted(has_set)))

if missing_any:
    print(f"{'SYMBOL':<16} {'MISSING':<25} HAS")
    print("-" * 60)
    for sym, miss, has in missing_any:
        print(f"  {sym:<14} {', '.join(miss):<25} {', '.join(has)}")
else:
    print("  All symbols have all 4 intervals.")

# ── 3. Latest candle per symbol×interval (staleness check) ───────────────────
print("\n" + "=" * 80)
print("STALENESS — latest candle per symbol x interval")
print("=" * 80)
cur.execute("""
    SELECT symbol, interval, MAX(ts)::date AS last_dt, COUNT(*) AS rows
    FROM candles
    GROUP BY symbol, interval
    ORDER BY last_dt ASC, symbol, interval
""")
rows = cur.fetchall()
today = date(2026, 5, 23)   # last trading day (Fri)
print(f"{'SYMBOL':<16} {'INTV':<6} {'LAST DATE':<14} {'ROWS':>8}  LAG")
print("-" * 55)
stale = []
for sym, iv, last, cnt in rows:
    lag = (today - last).days
    flag = f"  *** {lag}d BEHIND" if lag > 3 else ""
    if lag > 3:
        stale.append((sym, iv, last, lag))
    print(f"  {sym:<14} {iv:<6} {str(last):<14} {cnt:>8}{flag}")

# ── 4. Internal date gaps (daily only — practical to check) ──────────────────
print("\n" + "=" * 80)
print("INTERNAL DATE GAPS — 1d interval (missing trading days)")
print("=" * 80)

# Get all trading days we expect (from the most data-complete symbol)
cur.execute("""
    SELECT DISTINCT ts::date AS d
    FROM candles
    WHERE symbol='NIFTY' AND interval='1d'
    ORDER BY d
""")
nifty_days = {r[0] for r in cur.fetchall()}

cur.execute("SELECT DISTINCT symbol FROM candles WHERE interval='1d' ORDER BY symbol")
all_syms = [r[0] for r in cur.fetchall()]

gap_report = []
for sym in all_syms:
    cur.execute("""
        SELECT DISTINCT ts::date AS d FROM candles
        WHERE symbol=%s AND interval='1d'
        ORDER BY d
    """, (sym,))
    sym_days = {r[0] for r in cur.fetchall()}

    # Compare against NIFTY trading days within sym's own range
    if not sym_days:
        continue
    sym_start = min(sym_days)
    sym_end   = max(sym_days)

    # Expected = NIFTY days within sym range
    expected_days = {d for d in nifty_days if sym_start <= d <= sym_end}
    missing_days  = sorted(expected_days - sym_days)

    if missing_days:
        gap_report.append((sym, len(missing_days), missing_days[:5]))

if gap_report:
    print(f"{'SYMBOL':<16} {'MISSING_DAYS':>12}  FIRST FEW MISSING DATES")
    print("-" * 70)
    for sym, cnt, sample in gap_report:
        dates_str = ", ".join(str(d) for d in sample)
        more = f" ... +{cnt-5} more" if cnt > 5 else ""
        print(f"  {sym:<14} {cnt:>12}  {dates_str}{more}")
else:
    print("  No internal date gaps found in 1d data.")

# ── 5. Intraday row count consistency check ───────────────────────────────────
print("\n" + "=" * 80)
print("INTRADAY ROW COUNT — symbols with significantly fewer rows than average")
print("=" * 80)
for iv in ("1m", "5m", "30m"):
    cur.execute("""
        SELECT symbol, COUNT(*) AS cnt
        FROM candles
        WHERE interval=%s
        GROUP BY symbol
        ORDER BY cnt
    """, (iv,))
    rows = cur.fetchall()
    if not rows:
        continue
    counts = [r[1] for r in rows]
    avg = sum(counts) / len(counts)
    threshold = avg * 0.7   # flag if <70% of average
    low = [(sym, cnt) for sym, cnt in rows if cnt < threshold]
    print(f"\n  [{iv}]  avg={avg:.0f}  threshold={threshold:.0f}")
    if low:
        for sym, cnt in low:
            pct = cnt / avg * 100
            print(f"    {sym:<16} {cnt:>8} rows  ({pct:.0f}% of avg) <<< LOW")
    else:
        print("    All symbols within 70% of average.")

# ── 6. Intraday start date consistency ───────────────────────────────────────
print("\n" + "=" * 80)
print("INTRADAY START DATE GAPS — symbols starting later than earliest")
print("=" * 80)
for iv in ("1m", "5m", "30m"):
    cur.execute("""
        SELECT symbol, MIN(ts)::date AS start_dt, MAX(ts)::date AS end_dt, COUNT(*) AS cnt
        FROM candles WHERE interval=%s
        GROUP BY symbol ORDER BY start_dt DESC
    """, (iv,))
    rows = cur.fetchall()
    if not rows:
        continue
    starts = [r[1] for r in rows]
    earliest = min(starts)
    late = [(sym, s, e, cnt) for sym, s, e, cnt in rows if (s - earliest).days > 10]
    print(f"\n  [{iv}]  earliest start: {earliest}")
    if late:
        print(f"  {'SYMBOL':<16} {'START':<14} {'END':<14} {'ROWS':>8}  DAYS LATE")
        for sym, s, e, cnt in late:
            days_late = (s - earliest).days
            print(f"    {sym:<14} {str(s):<14} {str(e):<14} {cnt:>8}  +{days_late}d")
    else:
        print("    All symbols start within 10 days of earliest.")

conn.close()
print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
