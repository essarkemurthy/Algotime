#!/usr/bin/env python3
"""Clean DB snapshot grouped by category with history buckets."""
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
today = date(2026, 5, 22)   # last trading day

def history(d1, d2):
    if not d1 or not d2: return "—"
    days = (d2 - d1).days
    if days >= 365*10: return f"{days//365}+ yrs"
    if days >= 365*2:  return f"{days/365:.1f} yrs"
    if days >= 365:    return f"{days/365:.1f} yr"
    if days >= 30:     return f"{round(days/30.4)} mo"
    return f"{days}d"

def bucket(d1):
    if not d1: return "—"
    days = (today - d1).days
    if days >= 365*10: return "10+ yr"
    if days >= 365*5:  return "5-10 yr"
    if days >= 365*3:  return "3-5 yr"
    if days >= 365*2:  return "2-3 yr"
    if days >= 365:    return "1-2 yr"
    if days >= 180:    return "6-12 mo"
    return "<6 mo"

# --- load all per-symbol data ---
cur.execute("""
    SELECT symbol, interval, MIN(ts)::date, MAX(ts)::date, COUNT(*)
    FROM candles GROUP BY symbol, interval ORDER BY symbol, interval
""")
raw = cur.fetchall()

# build dict: symbol -> {iv: (frm, to, cnt)}
from collections import defaultdict
sdata = defaultdict(dict)
for sym, iv, frm, to, cnt in raw:
    sdata[sym][iv] = (frm, to, cnt)

all_syms = sorted(sdata.keys())

# --- totals ---
cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), pg_size_pretty(pg_total_relation_size('candles')), pg_size_pretty(pg_database_size(current_database())) FROM candles")
total, nsyms, tsz, dbsz = cur.fetchone()

# --- categories ---
INDICES = [
    "NIFTY","BANKNIFTY","CNXIT","NIFTYNEXT50","NIFTYMIDCAP50",
    "NIFTYFINSERV","NIFTYMIDSELECT","NIFTYINFRA","NIFTYPSE","NIFTYJR","INDIAVIX"
]
NIFTY50 = [
    "ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJAJFINSV",
    "BAJFINANCE","BHARTIARTL","BPCL","BRITANNIA","CIPLA","COALINDIA","DIVISLAB",
    "DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HEROMOTOCO","HINDALCO",
    "HINDUNILVR","ICICIBANK","INDUSINDBK","INFY","ITC","JIOFIN","JSWSTEEL",
    "KOTAKBANK","LT","LUPIN","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
    "POWERGRID","RELIANCE","SBIN","SUNPHARMA","TATAMOTORS","TATASTEEL","TCS",
    "TECHM","TITAN","TRENT","ULTRACEMCO","WIPRO","COLPAL","GAIL","NIFTY"
]

def get_cat(sym):
    if sym in INDICES:  return "INDEX"
    if sym in NIFTY50:  return "NIFTY50"
    return "OTHER"

# ── HEADER ────────────────────────────────────────────────────────────────────
print("=" * 78)
print("  DATABASE SNAPSHOT  —  market_data  @  localhost:5432  (PostgreSQL 18)")
print("=" * 78)
print(f"  Total candles  : {total:>12,}")
print(f"  Symbols        : {nsyms:>12}")
print(f"  Table size     : {tsz:>12}")
print(f"  Database size  : {dbsz:>12}")
print(f"  Last trade day : {today}")
print()

# ── INTERVAL SUMMARY ──────────────────────────────────────────────────────────
print("  INTERVAL OVERVIEW")
print("  " + "-" * 60)
for iv, label in [("1d","Daily"),("30m","30-min"),("5m","5-min"),("1m","1-min")]:
    syms_with = [s for s in all_syms if iv in sdata[s]]
    if not syms_with: continue
    all_frm = min(sdata[s][iv][0] for s in syms_with)
    all_to  = max(sdata[s][iv][1] for s in syms_with)
    rows    = sum(sdata[s][iv][2] for s in syms_with)
    print(f"  {label:<10} {len(syms_with):>3} symbols  {history(all_frm,all_to):>8}  "
          f"({all_frm} to {all_to})  {rows:>10,} rows")
print()

# ── PER-CATEGORY DETAIL ───────────────────────────────────────────────────────
for cat_label, cat_syms in [
    ("INDICES", [s for s in all_syms if get_cat(s)=="INDEX"]),
    ("NIFTY 50 STOCKS", [s for s in all_syms if get_cat(s)=="NIFTY50" and s not in INDICES]),
    ("NIFTY NEXT 50 + OTHER STOCKS", [s for s in all_syms if get_cat(s)=="OTHER"]),
]:
    if not cat_syms: continue
    print(f"  {'='*74}")
    print(f"  {cat_label}  ({len(cat_syms)} symbols)")
    print(f"  {'='*74}")
    print(f"  {'SYMBOL':<16} {'1d HISTORY':<12} {'30m':<8} {'5m':<8} {'1m':<8}  {'BUCKET'}")
    print("  " + "-" * 68)
    for sym in sorted(cat_syms):
        d = sdata[sym]
        d1_frm = d.get("1d",(None,None,0))[0]
        d1_to  = d.get("1d",(None,None,0))[1]
        hist1d = history(d1_frm, d1_to)
        h30    = history(*d["30m"][:2]) if "30m" in d else "—"
        h5     = history(*d["5m"][:2])  if "5m"  in d else "—"
        h1     = history(*d["1m"][:2])  if "1m"  in d else "—"
        bkt    = bucket(d1_frm)
        print(f"  {sym:<16} {hist1d:<12} {h30:<8} {h5:<8} {h1:<8}  {bkt}")
    print()

# ── HISTORY BUCKET SUMMARY ────────────────────────────────────────────────────
print("  " + "=" * 74)
print("  SYMBOLS BY DAILY HISTORY DEPTH  (1d interval)")
print("  " + "=" * 74)
from collections import Counter
bkts = Counter()
for sym in all_syms:
    if "1d" in sdata[sym]:
        bkts[bucket(sdata[sym]["1d"][0])] += 1

for b in ["10+ yr","5-10 yr","3-5 yr","2-3 yr","1-2 yr","6-12 mo","<6 mo"]:
    if bkts[b]:
        syms_in = [s for s in all_syms if "1d" in sdata[s] and bucket(sdata[s]["1d"][0])==b]
        print(f"  {b:<10} {bkts[b]:>3} symbols : {', '.join(syms_in)}")

conn.close()
print("\n" + "=" * 78)
