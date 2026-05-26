#!/usr/bin/env python3
"""Generate DB coverage markdown document."""
import os, sys
from pathlib import Path
from datetime import date
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import psycopg2

conn = psycopg2.connect(os.environ["DB_URL"])
cur = conn.cursor()

# interval coverage
cur.execute("""
    SELECT symbol,
           bool_or(interval='1d')  AS has_1d,
           bool_or(interval='30m') AS has_30m,
           bool_or(interval='5m')  AS has_5m,
           bool_or(interval='1m')  AS has_1m
    FROM candles
    GROUP BY symbol
    ORDER BY symbol
""")
cov = {sym: (d,t,f,m) for sym,d,t,f,m in cur.fetchall()}

# per-symbol date ranges
cur.execute("""
    SELECT symbol, interval, MIN(ts)::date, MAX(ts)::date, COUNT(*)
    FROM candles GROUP BY symbol, interval
""")
raw = cur.fetchall()
from collections import defaultdict
sdata = defaultdict(dict)
for sym, iv, frm, to, cnt in raw:
    sdata[sym][iv] = (frm, to, cnt)

# totals
cur.execute("""SELECT COUNT(*), COUNT(DISTINCT symbol),
    pg_size_pretty(pg_total_relation_size('candles')),
    pg_size_pretty(pg_database_size(current_database()))
    FROM candles""")
total, nsyms, tsz, dbsz = cur.fetchone()
conn.close()

def hist(d1, d2):
    if not d1 or not d2: return "—"
    days = (d2 - d1).days
    if days >= 365*10: return f"{days//365}+ yrs"
    if days >= 365*2:  return f"{days/365:.1f} yrs"
    if days >= 365:    return f"{days/365:.1f} yr"
    if days >= 30:     return f"{round(days/30.4)} mo"
    return f"{days}d"

INDICES = {"NIFTY","BANKNIFTY","CNXIT","NIFTYNEXT50","NIFTYMIDCAP50",
           "NIFTYFINSERV","NIFTYMIDSELECT","NIFTYINFRA","NIFTYPSE","NIFTYJR","INDIAVIX"}
NIFTY50 = {"ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO","BAJAJFINSV",
           "BAJFINANCE","BHARTIARTL","BPCL","BRITANNIA","CIPLA","COALINDIA","DIVISLAB",
           "DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK","HEROMOTOCO","HINDALCO",
           "HINDUNILVR","ICICIBANK","INDUSINDBK","INFY","ITC","JIOFIN","JSWSTEEL",
           "KOTAKBANK","LT","LUPIN","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
           "POWERGRID","RELIANCE","SBIN","SUNPHARMA","TATAMOTORS","TATASTEEL","TCS",
           "TECHM","TITAN","TRENT","ULTRACEMCO","WIPRO","COLPAL","GAIL","NIFTY"}

def cat(sym):
    if sym in INDICES: return "INDEX"
    if sym in NIFTY50: return "NIFTY50"
    return "OTHER"

tick = lambda x: "Y" if x else "N"
today = date(2026, 5, 22)

out = []
w = out.append

w("# Market Data Coverage Report")
w(f"\n**Generated:** {date(2026,5,24)}  |  **Last trade day:** {today}  |  **DB:** market_data @ localhost:5432 (PostgreSQL 18)\n")

w("## Database Summary\n")
w("| Metric | Value |")
w("|--------|-------|")
w(f"| Total candles | {total:,} |")
w(f"| Symbols | {nsyms} |")
w(f"| Table size | {tsz} |")
w(f"| Database size | {dbsz} |")

w("\n## Interval Overview\n")
w("| Interval | Symbols | Depth | Date Range | Rows |")
w("|----------|---------|-------|------------|------|")
for iv, label in [("1d","Daily"),("30m","30-min"),("5m","5-min"),("1m","1-min")]:
    syms = [s for s in cov if cov[s][["1d","30m","5m","1m"].index(iv)]]
    if not syms: continue
    frm = min(sdata[s][iv][0] for s in syms if iv in sdata[s])
    to  = max(sdata[s][iv][1] for s in syms if iv in sdata[s])
    rows = sum(sdata[s][iv][2] for s in syms if iv in sdata[s])
    w(f"| {label} | {len(syms)} | {hist(frm,to)} | {frm} to {to} | {rows:,} |")

w("\n## Complete Coverage (123 symbols — all 4 intervals)\n")
complete = [s for s in sorted(cov) if all(cov[s])]
w(f"**{len(complete)} symbols** have 1d + 30m + 5m + 1m data.\n")

for cat_label, cat_filter in [
    ("NSE Indices", lambda s: cat(s)=="INDEX"),
    ("Nifty 50 Stocks", lambda s: cat(s)=="NIFTY50" and s not in INDICES),
    ("Nifty Next 50 + Other Stocks", lambda s: cat(s)=="OTHER"),
]:
    grp = [s for s in complete if cat_filter(s)]
    if not grp: continue
    w(f"\n### {cat_label} ({len(grp)} symbols)\n")
    w("| Symbol | 1d History | 30m | 5m | 1m |")
    w("|--------|-----------|-----|----|----|")
    for s in grp:
        d = sdata[s]
        h1d = hist(d.get("1d",(None,None))[0], d.get("1d",(None,None))[1])
        h30 = hist(*d["30m"][:2]) if "30m" in d else "—"
        h5  = hist(*d["5m"][:2])  if "5m"  in d else "—"
        h1  = hist(*d["1m"][:2])  if "1m"  in d else "—"
        w(f"| {s} | {h1d} | {h30} | {h5} | {h1} |")

w("\n## Incomplete Coverage (3 symbols)\n")
w("These symbols are missing intraday intervals due to Breeze API limitations — not fixable.\n")
w("| Symbol | Category | 1d | 30m | 5m | 1m | Missing |")
w("|--------|----------|----|----|----|----|---------|")
incomplete = [(s, cov[s]) for s in sorted(cov) if not all(cov[s])]
for s, (d,t,f,m) in incomplete:
    missing = ", ".join(iv for iv,flag in [("1d",d),("30m",t),("5m",f),("1m",m)] if not flag)
    w(f"| {s} | {cat(s)} | {tick(d)} | {tick(t)} | {tick(f)} | {tick(m)} | {missing} |")

w("\n## History Depth Summary (Daily / 1d)\n")
w("| Bucket | Count | Symbols |")
w("|--------|-------|---------|")
buckets = [
    ("10+ yr",  lambda d: (today-d).days >= 365*10),
    ("5-10 yr", lambda d: 365*5  <= (today-d).days < 365*10),
    ("3-5 yr",  lambda d: 365*3  <= (today-d).days < 365*5),
    ("2-3 yr",  lambda d: 365*2  <= (today-d).days < 365*3),
    ("1-2 yr",  lambda d: 365    <= (today-d).days < 365*2),
    ("6-12 mo", lambda d: 180    <= (today-d).days < 365),
    ("<6 mo",   lambda d: (today-d).days < 180),
]
for label, fn in buckets:
    grp = [s for s in sorted(cov) if "1d" in sdata[s] and fn(sdata[s]["1d"][0])]
    if grp:
        w(f"| {label} | {len(grp)} | {', '.join(grp)} |")

doc_path = ROOT / "DB_COVERAGE.md"
with open(doc_path, "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

print(f"Written: {doc_path}")
