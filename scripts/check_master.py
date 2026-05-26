#!/usr/bin/env python3
"""Check Breeze master file for correct stock codes of zero-return Nifty50 stocks."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.load(open(ROOT / "data" / "symbols.json"))

# Zero-return Nifty50 stocks from extend_history.py
ZERO_RETURN = [
    "RELIANCE","HDFCBANK","INFY","ICICIBANK","HINDUNILVR",
    "SBIN","BHARTIARTL","KOTAKBANK","AXISBANK","LT",
    "ASIANPAINT","SUNPHARMA","ULTRACEMCO","NESTLEIND","POWERGRID",
    "COALINDIA","TATAMOTORS","TATASTEEL","HCLTECH","BAJFINANCE",
    "DRREDDY","BRITANNIA","HINDALCO","BAJAJFINSV",
    "M&M","BAJAJ-AUTO","EICHERMOT","HEROMOTOCO","TITAN",
    "ADANIPORTS","JSWSTEEL","TECHM","DIVISLAB","WIPRO",
    "INDUSINDBK","APOLLOHOSP","BPCL","CIPLA","ONGC",
]

# Already working symbols
WORKING = {
    "NIFTY","CNXIT","CIPLA","COLPAL","GRASIM","ITC","JIOFIN",
    "LUPIN","MARUTI","NTPC","ONGC","TCS","TRENT","WIPRO",
    "BIOCON","PIIND","GAIL",
}

nse_eq = [d for d in data if d.get("exchange") == "NSE" and d.get("product_type") == "Equity"]
bse_eq = [d for d in data if d.get("exchange") == "BSE" and d.get("product_type") == "Equity"]

print(f"NSE Equities: {len(nse_eq)}")
print(f"BSE Equities: {len(bse_eq)}")
print()
print(f"{'TARGET':<18} {'NSE_CODE':<20} {'BSE_CODE':<20} COMPANY")
print("-" * 90)

for t in ZERO_RETURN:
    nse_exact = [d for d in nse_eq if d.get("stock_code","").upper() == t.upper()]
    bse_exact = [d for d in bse_eq if d.get("stock_code","").upper() == t.upper()]

    # Try fuzzy if no exact match
    if not nse_exact:
        # try stripping special chars
        t_clean = t.replace("&","").replace("-","").replace(" ","")
        nse_exact = [d for d in nse_eq if d.get("stock_code","").upper().replace("-","").replace("&","") == t_clean.upper()]

    nse_code = nse_exact[0]["stock_code"] if nse_exact else "---"
    bse_code = bse_exact[0]["stock_code"] if bse_exact else "---"
    company = (nse_exact or bse_exact or [{}])[0].get("company_name","?")[:45]
    flag = "" if (nse_exact or bse_exact) else " <<< NOT FOUND"
    print(f"{t:<18} {nse_code:<20} {bse_code:<20} {company}{flag}")

print()
print("=" * 90)
print("Checking WORKING symbols for reference:")
print("=" * 90)
for s in sorted(WORKING):
    nse = [d for d in nse_eq if d.get("stock_code","").upper() == s.upper()]
    code = nse[0]["stock_code"] if nse else "NOT FOUND"
    company = nse[0].get("company_name","?")[:45] if nse else ""
    print(f"  {s:<16} {code:<20} {company}")
