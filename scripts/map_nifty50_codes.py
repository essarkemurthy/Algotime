#!/usr/bin/env python3
"""Map NSE Nifty50 tickers to correct Breeze stock_codes from symbols.json master file."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.load(open(ROOT / "data" / "symbols.json"))

nse_eq = {d["stock_code"]: d for d in data if d.get("exchange") == "NSE" and d.get("product_type") == "Equity"}

# Manual mapping: NSE ticker -> Breeze stock_code (from master file search)
# fmt: off
NIFTY50_MAP = {
    # Known working (already have data)
    "NIFTY":      "NIFTY",    # NIFTY 50
    "CNXIT":      "CNXIT",    # NIFTY IT
    "CIPLA":      "CIPLA",    # CIPLA LIMITED
    "COLPAL":     "COLPAL",   # COLGATE
    "GRASIM":     "GRASIM",   # GRASIM
    "ITC":        "ITC",      # ITC
    "JIOFIN":     "JIOFIN",   # JIO FINANCIAL
    "LUPIN":      "LUPIN",    # LUPIN
    "MARUTI":     "MARUTI",   # MARUTI SUZUKI
    "NTPC":       "NTPC",     # NTPC
    "ONGC":       "ONGC",     # ONGC
    "TCS":        "TCS",      # TCS
    "TRENT":      "TRENT",    # TRENT
    "WIPRO":      "WIPRO",    # WIPRO
    "BIOCON":     "BIOCON",   # BIOCON
    "PIIND":      "PIIND",    # PI INDUSTRIES
    "GAIL":       "GAIL",     # GAIL

    # Zero-return stocks — Breeze proprietary codes
    "RELIANCE":   "RELIND",   # RELIANCE INDUSTRIES
    "HDFCBANK":   "HDFBAN",   # HDFC BANK LIMITED
    "INFY":       None,       # need to find
    "ICICIBANK":  None,       # need to find
    "HINDUNILVR": None,       # need to find
    "SBIN":       None,       # need to find
    "BHARTIARTL": None,       # need to find
    "KOTAKBANK":  None,       # need to find
    "AXISBANK":   None,       # need to find
    "LT":         None,       # Larsen & Toubro
    "ASIANPAINT": None,       # need to find
    "SUNPHARMA":  None,       # need to find
    "ULTRACEMCO": None,       # need to find
    "NESTLEIND":  None,       # need to find
    "POWERGRID":  None,       # need to find
    "COALINDIA":  None,       # need to find
    "TATAMOTORS": None,       # need to find
    "TATASTEEL":  None,       # need to find
    "HCLTECH":    None,       # need to find
    "BAJFINANCE": None,       # need to find
    "DRREDDY":    None,       # need to find
    "BRITANNIA":  None,       # need to find
    "HINDALCO":   None,       # need to find
    "BAJAJFINSV": None,       # need to find
    "M&M":        None,       # Mahindra
    "BAJAJ-AUTO": None,       # Bajaj Auto
    "EICHERMOT":  None,       # Eicher Motors
    "HEROMOTOCO": None,       # Hero MotoCorp
    "TITAN":      None,       # Titan
    "ADANIPORTS": None,       # Adani Ports
    "JSWSTEEL":   None,       # JSW Steel
    "TECHM":      None,       # Tech Mahindra
    "DIVISLAB":   None,       # Divi's Lab
    "INDUSINDBK": None,       # IndusInd Bank
    "APOLLOHOSP": None,       # Apollo Hospitals
    "BPCL":       None,       # BPCL
    "HCLTECH":    None,       # HCL Tech
}
# fmt: on

# Search terms for company name lookup
COMPANY_SEARCH = {
    "INFY":       "INFOSYS",
    "ICICIBANK":  "ICICI BANK",
    "HINDUNILVR": "HINDUSTAN UNILEVER",
    "SBIN":       "STATE BANK",
    "BHARTIARTL": "BHARTI AIRTEL",
    "KOTAKBANK":  "KOTAK MAHINDRA BANK",
    "AXISBANK":   "AXIS BANK",
    "LT":         "LARSEN",
    "ASIANPAINT": "ASIAN PAINTS",
    "SUNPHARMA":  "SUN PHARMA",
    "ULTRACEMCO": "ULTRATECH CEMENT",
    "NESTLEIND":  "NESTLE",
    "POWERGRID":  "POWER GRID",
    "COALINDIA":  "COAL INDIA",
    "TATAMOTORS": "TATA MOTORS",
    "TATASTEEL":  "TATA STEEL",
    "HCLTECH":    "HCL TECH",
    "BAJFINANCE": "BAJAJ FINANCE",
    "DRREDDY":    "DR REDDY",
    "BRITANNIA":  "BRITANNIA",
    "HINDALCO":   "HINDALCO",
    "BAJAJFINSV": "BAJAJ FINSERV",
    "M&M":        "MAHINDRA",
    "BAJAJ-AUTO": "BAJAJ AUTO",
    "EICHERMOT":  "EICHER MOTORS",
    "HEROMOTOCO": "HERO MOTOCORP",
    "TITAN":      "TITAN COMPANY",
    "ADANIPORTS": "ADANI PORTS",
    "JSWSTEEL":   "JSW STEEL",
    "TECHM":      "TECH MAHINDRA",
    "DIVISLAB":   "DIVI",
    "INDUSINDBK": "INDUSIND BANK",
    "APOLLOHOSP": "APOLLO HOSPITALS",
    "BPCL":       "BHARAT PETROLEUM",
}

print("=" * 95)
print("NIFTY50 SYMBOL MAPPING — NSE ticker -> Breeze stock_code")
print("=" * 95)
print(f"{'NSE TICKER':<16} {'BREEZE CODE':<14} {'COMPANY':<50} STATUS")
print("-" * 95)

all_nse = [d for d in data if d.get("exchange") == "NSE" and d.get("product_type") == "Equity"]
final_map = {}

for nse_tick, breeze_code in NIFTY50_MAP.items():
    if breeze_code is not None:
        company = nse_eq.get(breeze_code, {}).get("company_name", "?")
        print(f"{nse_tick:<16} {breeze_code:<14} {company:<50} KNOWN")
        final_map[nse_tick] = breeze_code
        continue

    # Auto-search
    search_term = COMPANY_SEARCH.get(nse_tick, nse_tick)
    matches = [d for d in all_nse if search_term.upper() in d.get("company_name", "").upper()]
    # filter out ETFs, rights entitlements etc
    core = [m for m in matches if not any(x in m.get("company_name","").upper()
            for x in ("ETF","FUND","WARRANT","RIGHTS","ENTITL","BOND","SCHEME","TRUST"))]

    if core:
        best = sorted(core, key=lambda d: len(d.get("company_name","")))[0]
        print(f"{nse_tick:<16} {best['stock_code']:<14} {best['company_name']:<50} AUTO-FOUND")
        final_map[nse_tick] = best["stock_code"]
    elif matches:
        best = matches[0]
        print(f"{nse_tick:<16} {best['stock_code']:<14} {best['company_name']:<50} FUZZY")
        final_map[nse_tick] = best["stock_code"]
    else:
        print(f"{nse_tick:<16} {'???':<14} {'NOT FOUND':<50} MISSING")

print()
print("=" * 95)
print("PYTHON DICT FOR bulk_download.py:")
print("=" * 95)
print("NSE_TICKER_TO_BREEZE = {")
for k, v in final_map.items():
    print(f'    "{k}": "{v}",')
print("}")
