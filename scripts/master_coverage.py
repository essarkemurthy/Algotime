#!/usr/bin/env python3
"""
Analyse symbols.json master file vs what's in DB.
Find all NSE indices + high-value stocks not yet downloaded.
"""
import json, os, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
conn = psycopg2.connect(os.environ["DB_URL"])
cur = conn.cursor()

# ── What's already in DB ──────────────────────────────────────────────────────
cur.execute("SELECT DISTINCT symbol FROM candles")
in_db = {r[0] for r in cur.fetchall()}

cur.execute("""
    SELECT symbol, array_agg(DISTINCT interval ORDER BY interval) AS ivs,
           MIN(ts)::date, MAX(ts)::date, COUNT(*)
    FROM candles GROUP BY symbol
""")
db_detail = {r[0]: {"ivs": r[1], "from": r[2], "to": r[3], "rows": r[4]}
             for r in cur.fetchall()}
conn.close()

# ── Load master file ──────────────────────────────────────────────────────────
data = json.load(open(ROOT / "data" / "symbols.json"))

nse_eq  = [d for d in data if d["exchange"] == "NSE"  and d["product_type"] == "Equity"]
bse_eq  = [d for d in data if d["exchange"] == "BSE"  and d["product_type"] == "Equity"]

# Build lookup: company_name keyword -> rows
def search(keyword, pool):
    kw = keyword.upper()
    return [d for d in pool if kw in d.get("stock_code","").upper()
            or kw in d.get("company_name","").upper()]

# ── 1. Current DB snapshot ────────────────────────────────────────────────────
print("=" * 80)
print("CURRENT DB SNAPSHOT")
print("=" * 80)
print(f"Symbols in DB : {len(in_db)}")
print(f"{'SYMBOL':<16} {'INTERVALS':<22} {'FROM':<12} {'TO':<12} {'ROWS':>9}")
print("-" * 75)
for sym in sorted(in_db):
    d = db_detail[sym]
    print(f"{sym:<16} {', '.join(d['ivs']):<22} {str(d['from']):<12} {str(d['to']):<12} {d['rows']:>9,}")

# ── 2. NSE Indices available in master ───────────────────────────────────────
print("\n" + "=" * 80)
print("NSE INDICES IN MASTER FILE — not yet in DB")
print("=" * 80)
nse_indices = [d for d in nse_eq if any(kw in d.get("company_name","").upper()
    for kw in ("NIFTY","SENSEX","BANK NIFTY","INDIA VIX")) or
    any(kw in d.get("stock_code","").upper()
    for kw in ("NIFTY","BKNIFTY","MIDCAP","SMLCAP","FINNIFTY","VIX"))]

missing_indices = [d for d in nse_indices if d["stock_code"] not in in_db]
print(f"{'CODE':<14} {'COMPANY':<50} IN_DB")
print("-" * 70)
for d in sorted(missing_indices, key=lambda x: x["stock_code"]):
    print(f"  {d['stock_code']:<12} {d['company_name']:<50} NO")

# ── 3. Nifty Next 50 stocks ───────────────────────────────────────────────────
NIFTY_NEXT50_NSE = [
    "ADANIENT","ADANIGREEN","ADANIPOWER","AMBUJACEM","ABB","ATGL","DMART","BAJAJHFL",
    "BANKBARODA","BEL","BHEL","BOSCHLTD","CANBK","CHOLAFIN","CIPLA","CONCOR",
    "DABUR","DLF","FEDERALBNK","GODREJCP","HAVELLS","HDFCLIFE","HINDPETRO","ICICIPRULI",
    "ICICIGI","IOC","IRCTC","IRFC","JINDALSTEL","MCDOWELL-N","MOTHERSON","MUTHOOTFIN",
    "NHPC","NMDC","NAUKRI","PIDILITIND","RECLTD","SAIL","SIEMENS","SRF",
    "TATACOMM","TATAPOWER","TORNTPHARM","TVSMOTOR","UPL","VBL","VEDL","ZOMATO",
    "ZYDUSLIFE","SHRIRAMFIN",
]

print("\n" + "=" * 80)
print("NIFTY NEXT 50 — missing from DB")
print("=" * 80)
missing_nn50 = []
for tick in sorted(NIFTY_NEXT50_NSE):
    if tick not in in_db:
        # Find Breeze code
        exact = [d for d in nse_eq if d["stock_code"].upper() == tick.upper()]
        if not exact:
            # Try partial
            clean = tick.replace("-","").replace("&","")
            exact = [d for d in nse_eq
                     if clean.upper() in d["stock_code"].upper()
                     or tick.upper().replace("-","") in d.get("company_name","").upper()[:20]]
        code = exact[0]["stock_code"] if exact else "???"
        company = exact[0].get("company_name","?")[:40] if exact else "NOT FOUND"
        missing_nn50.append((tick, code, company))
        print(f"  {tick:<18} {code:<14} {company}")

# ── 4. Broad NSE high-cap stocks from master not in DB ───────────────────────
# Find all NSE equity stocks with token numbers suggesting they are major listings
print("\n" + "=" * 80)
print("OTHER NOTABLE NSE STOCKS IN MASTER — not in DB (sample)")
print("=" * 80)
notable_keywords = [
    "PERSISTENT","MPHASIS","LTIM","LTTS","COFORGE","KPIT","POLICYBZR",
    "PAYTM","NYKAA","ZOMATO","IRCTC","DMART","PIDILITE","BERGEPAINT",
    "MARICO","GODREJCP","DABUR","EMAMILTD","TATACOMM","TATAPOWER",
    "ADANIENT","HAVELLS","VOLTAS","WHIRLPOOL","HONAUT",
    "BAJAJHFL","BANKBARODA","CANBK","UNIONBANK","IDFCFIRSTB",
    "MCDOWELL","RADICO","CHOLAFIN","MUTHOOTFIN","MANAPPURAM",
    "RECLTD","IRFC","NHPC","NMDC","SAIL","HINDZINC",
    "VEDL","JSL","NATIONALUM","MOIL",
]
print(f"{'NSE_TICKER':<18} {'BREEZE_CODE':<14} COMPANY")
print("-" * 70)
found_notable = []
for kw in notable_keywords:
    if kw in in_db:
        continue
    matches = [d for d in nse_eq
               if kw.upper() in d["stock_code"].upper()
               or kw.upper().replace("-","") in d.get("company_name","").upper()[:25]]
    core = [m for m in matches if not any(x in m.get("company_name","").upper()
            for x in ("ETF","FUND","WARRANT","RIGHTS","ENTITL","BOND","SCHEME"))]
    if core:
        best = sorted(core, key=lambda x: len(x.get("company_name","")))[0]
        found_notable.append((kw, best["stock_code"], best.get("company_name","")[:40]))
        print(f"  {kw:<16} {best['stock_code']:<14} {best['company_name'][:40]}")

# ── 5. Summary ────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SUMMARY — what can be downloaded next")
print("=" * 80)
print(f"  Indices missing from DB    : {len(missing_indices)}")
print(f"  Nifty Next 50 missing      : {len(missing_nn50)}")
print(f"  Other notable stocks       : {len(found_notable)}")
print(f"  Total potential new symbols: {len(missing_indices)+len(missing_nn50)+len(found_notable)}")
