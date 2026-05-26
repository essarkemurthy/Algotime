#!/usr/bin/env python3
"""Find correct Breeze codes for NSE indices + Nifty Next 50 stocks."""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
data = json.load(open(ROOT / "data" / "symbols.json"))
nse = [d for d in data if d["exchange"] == "NSE" and d["product_type"] == "Equity"]

def find(pool, *keywords, exact_code=None):
    if exact_code:
        m = [d for d in pool if d["stock_code"].upper() == exact_code.upper()]
        if m: return m[0]
    for kw in keywords:
        m = [d for d in pool if kw.upper() in d.get("company_name","").upper()
             and not any(x in d.get("company_name","").upper()
                         for x in ("ETF","FUND","WARRANT","RIGHTS","ENTITL","BOND","SCHEME","OFS"))]
        if m:
            return sorted(m, key=lambda x: len(x.get("company_name","")))[0]
    return None

# ── Real NSE indices (not ETFs) ───────────────────────────────────────────────
INDICES = [
    ("BANKNIFTY", "CNXBAN",  "NSE", "NIFTY BANK"),
    ("NIFTYNEXT50","NIFNEX", "NSE", "NIFTY NEXT 50"),
    ("NIFTYMIDCAP50","NIFMID","NSE","NIFTY MIDCAP 50"),
    ("NIFTYFINSERV","NIFFIN", "NSE","NIFTY FINANCIAL SERVICES"),
    ("NIFTYMIDSELECT","NIFSEL","NSE","NIFTY MIDCAP SELECT"),
    ("NIFTYINFRA","CNXINF",  "NSE","NIFTY INFRASTRUCTURE"),
    ("NIFTYPSE",  "CNXPSE",  "NSE","NIFTY PSE"),
    ("NIFTYJR",   "CNXNIF",  "NSE","CNX NIFTY JUNIOR"),
    ("INDIAVIX",  "INDVIX",  "NSE","INDIA VIX"),
]

# ── Nifty Next 50 — manual search by company name ─────────────────────────────
NN50_SEARCH = [
    ("ADANIENT",   ["ADANI ENTERPRISES LIMITED"]),
    ("ADANIGREEN", ["ADANI GREEN ENERGY"]),
    ("ADANIPOWER", ["ADANI POWER"]),
    ("AMBUJACEM",  ["AMBUJA CEMENTS"]),
    ("ABB",        ["ABB INDIA"]),
    ("ATGL",       ["ADANI TOTAL GAS"]),
    ("BAJAJHFL",   ["BAJAJ HOUSING FINANCE"]),
    ("BANKBARODA", ["BANK OF BARODA"]),
    ("BEL",        ["BHARAT ELECTRONICS"]),
    ("BHEL",       ["BHARAT HEAVY ELECTRICALS"]),
    ("BOSCHLTD",   ["BOSCH LIMITED","BOSCH LTD"]),
    ("CANBK",      ["CANARA BANK"]),
    ("CHOLAFIN",   ["CHOLAMANDALAM INVEST","CHOLAMANDALAM FIN"]),
    ("CONCOR",     ["CONTAINER CORPORATION"]),
    ("DABUR",      ["DABUR INDIA"]),
    ("DLF",        ["DLF LIMITED"]),
    ("DMART",      ["AVENUE SUPERMARTS","D-MART"]),
    ("FEDERALBNK", ["FEDERAL BANK"]),
    ("GODREJCP",   ["GODREJ CONSUMER"]),
    ("HAVELLS",    ["HAVELLS INDIA"]),
    ("HDFCLIFE",   ["HDFC LIFE INSURANCE"]),
    ("HINDPETRO",  ["HINDUSTAN PETROLEUM"]),
    ("ICICIGI",    ["ICICI LOMBARD GEN","ICICI GENERAL"]),
    ("ICICIPRULI", ["ICICI PRUDENTIAL LIFE"]),
    ("IOC",        ["INDIAN OIL CORPORATION"]),
    ("IRCTC",      ["INDIAN RAILWAY CATERING"]),
    ("IRFC",       ["INDIAN RAILWAY FINANCE"]),
    ("JINDALSTEL", ["JINDAL STEEL"]),
    ("MCDOWELL-N", ["UNITED SPIRITS"]),
    ("MOTHERSON",  ["SAMVARDHANA MOTHERSON","MOTHERSON SUMI SYS"]),
    ("MUTHOOTFIN", ["MUTHOOT FINANCE"]),
    ("NAUKRI",     ["INFO EDGE","NAUKRI"]),
    ("NHPC",       ["NHPC LIMITED"]),
    ("NMDC",       ["NMDC LIMITED"]),
    ("PIDILITIND", ["PIDILITE INDUSTRIES"]),
    ("RECLTD",     ["REC LIMITED","RURAL ELECTRIFICATION"]),
    ("SAIL",       ["STEEL AUTHORITY OF INDIA"]),
    ("SHRIRAMFIN", ["SHRIRAM FINANCE","SHRIRAM TRANSPORT"]),
    ("SIEMENS",    ["SIEMENS LTD","SIEMENS LIMITED"]),
    ("SRF",        ["SRF LIMITED"]),
    ("TATACOMM",   ["TATA COMMUNICATIONS"]),
    ("TATAPOWER",  ["TATA POWER"]),
    ("TORNTPHARM", ["TORRENT PHARMA"]),
    ("TVSMOTOR",   ["TVS MOTOR"]),
    ("UPL",        ["UPL LIMITED","UNITED PHOSPHORUS"]),
    ("VBL",        ["VARUN BEVERAGES"]),
    ("VEDL",       ["VEDANTA LIMITED"]),
    ("ZOMATO",     ["ZOMATO"]),
    ("ZYDUSLIFE",  ["ZYDUS LIFESCIENCES","CADILA HEALTH"]),
    ("SHRIRAMFIN", ["SHRIRAM FINANCE"]),
]

# ── Other notable midcap/smallcap ─────────────────────────────────────────────
OTHERS_SEARCH = [
    ("PERSISTENT", ["PERSISTENT SYSTEMS"]),
    ("MPHASIS",    ["MPHASIS"]),
    ("COFORGE",    ["COFORGE"]),
    ("KPIT",       ["KPIT TECHNOLOGIES"]),
    ("LTTS",       ["L&T TECHNOLOGY SERVICES","LT TECHNOLOGY"]),
    ("LTIM",       ["LTIMindtree","LARSEN AND TOUBRO INFOTECH"]),
    ("PIDILITE",   ["PIDILITE INDUSTRIES"]),
    ("MARICO",     ["MARICO LIMITED"]),
    ("BERGEPAINT", ["BERGER PAINTS"]),
    ("VOLTAS",     ["VOLTAS LTD","VOLTAS LIMITED"]),
    ("RADICO",     ["RADICO KHAITAN"]),
    ("MANAPPURAM", ["MANAPPURAM FINANCE"]),
    ("CHOLAFIN",   ["CHOLAMANDALAM INVEST"]),
    ("MUTHOOTFIN", ["MUTHOOT FINANCE"]),
    ("IDFCFIRSTB", ["IDFC FIRST BANK"]),
    ("HINDZINC",   ["HINDUSTAN ZINC"]),
    ("MOIL",       ["MOIL LIMITED"]),
    ("GODREJPROP", ["GODREJ PROPERTIES"]),
    ("OBEROIRLTY",  ["OBEROI REALTY"]),
    ("PRESTIGE",   ["PRESTIGE ESTATES"]),
]

print("=" * 80)
print("NSE INDICES — Breeze codes")
print("=" * 80)
print(f"  {'TICKER':<16} {'BREEZE':<10} STATUS")
for label, code, exch, desc in INDICES:
    r = find(nse, desc, exact_code=code)
    found = r["stock_code"] if r else "NOT FOUND"
    print(f"  {label:<16} {found:<10} {desc}")

print("\n" + "=" * 80)
print("NIFTY NEXT 50 — Breeze code mapping")
print("=" * 80)
print(f"  {'NSE_TICKER':<16} {'BREEZE':<10} COMPANY")
nn50_found = []
for ticker, kws in NN50_SEARCH:
    r = find(nse, *kws)
    if r:
        print(f"  {ticker:<16} {r['stock_code']:<10} {r['company_name'][:50]}")
        nn50_found.append((ticker, r["stock_code"], "NSE"))
    else:
        print(f"  {ticker:<16} {'???':<10} NOT FOUND (searched: {kws[0]})")

print("\n" + "=" * 80)
print("OTHER NOTABLE STOCKS — Breeze code mapping")
print("=" * 80)
others_found = []
for ticker, kws in OTHERS_SEARCH:
    r = find(nse, *kws)
    if r:
        print(f"  {ticker:<16} {r['stock_code']:<10} {r['company_name'][:50]}")
        others_found.append((ticker, r["stock_code"], "NSE"))
    else:
        print(f"  {ticker:<16} {'???':<10} NOT FOUND")

# Print download list
all_download = (
    [(lbl, code, exch) for lbl,code,exch,_ in INDICES] +
    nn50_found +
    others_found
)
print("\n" + "=" * 80)
print("DOWNLOAD LIST (copy into download script):")
print("=" * 80)
for t, c, e in all_download:
    print(f'    ("{c}", "{e}", "{t}"),')
