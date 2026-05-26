#!/usr/bin/env python3
"""Clean human-readable snapshot of all downloaded data."""
import os, sys
from pathlib import Path
from datetime import date
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import psycopg2

conn = psycopg2.connect(os.environ["DB_URL"])
cur  = conn.cursor()

today = date.today()

def dur(d1, d2):
    if not d1 or not d2: return "—"
    days = (d2 - d1).days
    if days >= 365*2: return f"{days/365:.1f} yrs"
    if days >= 30:    return f"{round(days/30.4)} mo"
    return f"{days}d"

# ── Summary ───────────────────────────────────────────────────────────────────
cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), pg_size_pretty(pg_total_relation_size('candles')) FROM candles")
total, nsyms, sz = cur.fetchone()
print(f"\n{'='*80}")
print(f"  DB SNAPSHOT   {today}   |   {total:,} candles   {nsyms} symbols   {sz}")
print(f"{'='*80}")

# ── Per symbol detail ─────────────────────────────────────────────────────────
cur.execute("""
    SELECT symbol,
           array_agg(DISTINCT interval ORDER BY interval) AS ivs,
           MIN(ts)::date, MAX(ts)::date, COUNT(*) AS rows
    FROM candles
    GROUP BY symbol
    ORDER BY symbol
""")
rows = cur.fetchall()

# Group by category
nifty50 = {
    "ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJAJFINSV",
    "BAJFINANCE","BHARTIARTL","BPCL","BRITANNIA","CIPLA","COALINDIA","DIVISLAB",
    "DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HEROMOTOCO","HINDALCO",
    "HINDUNILVR","ICICIBANK","INDUSINDBK","INFY","ITC","JIOFIN","JSWSTEEL",
    "KOTAKBANK","LT","LUPIN","M&M","MARUTI","NESTLEIND","NIFTY","NTPC","ONGC",
    "POWERGRID","RELIANCE","SBIN","SUNPHARMA","TATAMOTORS","TATASTEEL","TCS",
    "TECHM","TITAN","TRENT","ULTRACEMCO","WIPRO","COLPAL","GAIL",
}
indices = {
    "NIFTY","CNXIT","BANKNIFTY","NIFTYNEXT50","NIFTYMIDCAP50","NIFTYFINSERV",
    "NIFTYMIDSELECT","NIFTYINFRA","NIFTYPSE","NIFTYJR","INDIAVIX",
}

def tag(sym):
    if sym in indices:   return "INDEX"
    if sym in nifty50:   return "N50"
    return "OTHER"

hdr = f"  {'SYMBOL':<16} {'TAG':<7} {'1d':^14} {'30m':^12} {'5m':^12} {'1m':^12}  ROWS"
sep = "  " + "-"*78
print(hdr)
print(sep)

for sym, ivs, frm, to, cnt in rows:
    iv_set = set(ivs)
    def span(iv):
        if iv not in iv_set: return "—"*12
        # get per-interval range
        cur2 = conn.cursor()
        cur2.execute("""SELECT MIN(ts)::date, MAX(ts)::date FROM candles
                        WHERE symbol=%s AND interval=%s""", (sym, iv))
        r = cur2.fetchone()
        if not r or not r[0]: return "—"*12
        return f"{dur(r[0],r[1]):>6} ({r[0].strftime('%b%y')})"
    t = tag(sym)
    print(f"  {sym:<16} {t:<7} {span('1d'):^14} {span('30m'):^12} {span('5m'):^12} {span('1m'):^12}  {cnt:>8,}")

# ── Summary by category ───────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("  SUMMARY BY CATEGORY")
print(f"{'='*80}")
syms_in_db = {r[0] for r in rows}
for cat, s in [("Indices", indices & syms_in_db),
               ("Nifty50", nifty50 & syms_in_db),
               ("Other",   syms_in_db - indices - nifty50)]:
    print(f"  {cat:<10} {len(s):>3} symbols")

# ── Intervals coverage ────────────────────────────────────────────────────────
print(f"\n{'='*80}")
print("  INTERVAL COVERAGE")
print(f"{'='*80}")
for iv in ("1d","30m","5m","1m"):
    cur.execute("""SELECT COUNT(DISTINCT symbol), MIN(ts)::date, MAX(ts)::date
                   FROM candles WHERE interval=%s""", (iv,))
    c, mn, mx = cur.fetchone()
    print(f"  {iv:<5}  {c:>3} symbols   {dur(mn,mx):>8}  ({mn} to {mx})")

conn.close()
print(f"\n{'='*80}\n")
