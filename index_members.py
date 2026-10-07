"""Index constituents, keyed by the WATCHLIST label of each index.

Used by /api/index/members so the Live spot detail pane can list every stock in
a chosen index. Tickers are NSE symbols spelled the way this project labels
them (ETERNAL not ZOMATO, M&M, BAJAJ-AUTO). Lists reflect the NSE/BSE
reconstitutions known as of October 2026; indices rebalance twice a year
(March/September), so refresh these when a reshuffle is announced.

Membership here is independent of the live feed: a constituent that is not in
WATCHLIST still appears in the pane, just without a price, so the view answers
"what is in this index" rather than "what do we happen to stream".
"""
from __future__ import annotations

from typing import Dict, List

INDICES: Dict[str, dict] = {
    "NIFTY": {
        "name": "Nifty 50",
        "members": [
            "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
            "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
            "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
            "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
            "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC",
            "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
            "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
            "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
            "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL",
            "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
        ],
    },
    "BANKNIFTY": {
        "name": "Nifty Bank",
        "members": [
            "AUBANK", "AXISBANK", "BANKBARODA", "CANBK", "FEDERALBNK",
            "HDFCBANK", "ICICIBANK", "IDFCFIRSTB", "INDUSINDBK", "KOTAKBANK",
            "PNB", "SBIN",
        ],
    },
    "NIFTYFINSERVICE": {
        "name": "Nifty Financial Services",
        "members": [
            "AXISBANK", "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "HDFCAMC",
            "HDFCBANK", "HDFCLIFE", "ICICIBANK", "ICICIGI", "ICICIPRULI",
            "JIOFIN", "KOTAKBANK", "LICHSGFIN", "MUTHOOTFIN", "PFC",
            "RECLTD", "SBICARD", "SBILIFE", "SBIN", "SHRIRAMFIN",
        ],
    },
    "CNXIT": {
        "name": "Nifty IT",
        "members": [
            "COFORGE", "HCLTECH", "INFY", "LTIM", "MPHASIS",
            "OFSS", "PERSISTENT", "TCS", "TECHM", "WIPRO",
        ],
    },
    "MIDCPNIFTY": {
        "name": "Nifty Midcap Select",
        "members": [
            "ASHOKLEY", "AUBANK", "AUROPHARMA", "BHARATFORG", "COFORGE",
            "COLPAL", "CONCOR", "CUMMINSIND", "DIXON", "FEDERALBNK",
            "GODREJPROP", "HDFCAMC", "HINDPETRO", "IDEA", "IDFCFIRSTB",
            "INDHOTEL", "LUPIN", "MARICO", "MPHASIS", "MRF",
            "PAGEIND", "PERSISTENT", "POLYCAB", "UPL", "VOLTAS",
        ],
    },
    "NIFTYNEXT50": {
        "name": "Nifty Next 50",
        "members": [
            "ABB", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM",
            "BAJAJHFL", "BAJAJHLDNG", "BANKBARODA", "BOSCHLTD", "BPCL",
            "BRITANNIA", "CANBK", "CGPOWER", "CHOLAFIN", "DABUR",
            "DIVISLAB", "DLF", "DMART", "GAIL", "GODREJCP",
            "HAL", "HAVELLS", "HEROMOTOCO", "HYUNDAI", "ICICIGI",
            "ICICIPRULI", "INDHOTEL", "INDUSINDBK", "IOC", "IRFC",
            "JINDALSTEL", "JSWENERGY", "LICI", "LODHA", "LTIM",
            "MOTHERSON", "NAUKRI", "PFC", "PIDILITIND", "PNB",
            "RECLTD", "SHREECEM", "SIEMENS", "SWIGGY", "TATAPOWER",
            "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", "VEDL",
        ],
    },
    "SENSEX": {
        "name": "BSE Sensex",
        "members": [
            "ADANIPORTS", "ASIANPAINT", "AXISBANK", "BAJFINANCE", "BAJAJFINSV",
            "BEL", "BHARTIARTL", "ETERNAL", "HCLTECH", "HDFCBANK",
            "HINDUNILVR", "ICICIBANK", "INFY", "ITC", "KOTAKBANK",
            "LT", "M&M", "MARUTI", "NTPC", "POWERGRID",
            "RELIANCE", "SBIN", "SUNPHARMA", "TCS", "TATAMOTORS",
            "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
        ],
    },
}


def members(index_symbol: str) -> List[str]:
    """Constituents of an index by WATCHLIST label; empty list if unknown."""
    meta = INDICES.get(str(index_symbol or "").upper())
    return list(meta["members"]) if meta else []
