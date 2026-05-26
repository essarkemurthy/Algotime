# Algotime — Data Coverage Report
**Generated:** 27-May-2026 · **Database:** PostgreSQL `market_data`

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total candles in DB | **4,525,250** |
| Total symbols in DB | **164** |
| DB history from | 13-Sep-2012 |
| DB history to | 26-May-2026 (~14 years) |
| Nifty 50 coverage | **50 / 51** symbols (LTIM unavailable in Breeze) |
| Bank Nifty coverage | **10 / 12** symbols (AUBANK, PNB missing) |
| Intervals available | 1-minute · 5-minute · 30-minute · 1-day |

---

## Nifty 50 — Coverage Analysis

**Index composition:** 51 current constituents · **50 available in DB** · 1 unavailable

> **Note on ETERNAL:** Zomato Ltd was renamed to Eternal Ltd in Feb 2025. The DB holds `ZOMATO` (Jul-2021 → May-2026 full history) and `ETERNAL` (post-rename ticker from May-2025). Both are present.

### Symbol-by-Symbol Status

| # | Symbol | Status | Data From | Data To | Total Candles | Intervals | 1d | 30m | 5m | 1m |
|---|--------|--------|-----------|---------|---------------|-----------|-----|-----|----|----|
| 1 | ADANIENT | ✅ Full | 17-Sep-2012 | 22-May-2026 | 35,742 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,294 | 15,000 |
| 2 | ADANIPORTS | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 3 | APOLLOHOSP | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 4 | ASIANPAINT | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,449 | 1m 5m 30m 1d | 3,378 | 3,071 | 14,000 | 15,000 |
| 5 | AXISBANK | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 6 | BAJAJ-AUTO | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 7 | BAJAJFINSV | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 8 | BAJFINANCE | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 9 | BEL | ✅ Full | 17-Sep-2012 | 22-May-2026 | 35,742 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,294 | 15,000 |
| 10 | BHARTIARTL | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 11 | BPCL | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 12 | BRITANNIA | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,446 | 1m 5m 30m 1d | 3,375 | 3,071 | 14,000 | 15,000 |
| 13 | CIPLA | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 14 | COALINDIA | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 15 | DRREDDY | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 16 | EICHERMOT | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 17 | ETERNAL ¹ | ⚠️ Partial | 28-May-2025 | 26-May-2026 | 17,318 | 5m 30m 1d | 247 | 3,071 | 14,000 | — |
| 18 | GRASIM | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 19 | HCLTECH | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 20 | HDFCBANK | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 21 | HDFCLIFE ² | ✅ Since IPO | 17-Nov-2017 | 22-May-2026 | 33,467 | 1m 5m 30m 1d | 2,102 | 3,071 | 14,294 | 14,000 |
| 22 | HEROMOTOCO | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 23 | HINDALCO | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 24 | HINDUNILVR | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 25 | ICICIBANK | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 26 | INDUSINDBK | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 27 | INFY | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 28 | ITC | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 29 | JIOFIN ³ | ✅ Since listing | 21-Aug-2023 | 26-May-2026 | 37,042 | 1m 5m 30m 1d | 685 | 3,227 | 15,130 | 18,000 |
| 30 | JSWSTEEL | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 31 | KOTAKBANK | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 32 | LT | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 33 | LTIM | ❌ Missing | — | — | — | — | — | — | — | — |
| 34 | MARUTI | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 35 | NESTLEIND | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 36 | NTPC | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 37 | ONGC | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 38 | POWERGRID | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 39 | RELIANCE | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 40 | SBIN | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 41 | SBILIFE ² | ⚠️ Partial | 28-May-2025 | 26-May-2026 | 17,318 | 5m 30m 1d | 247 | 3,071 | 14,000 | — |
| 42 | SHRIRAMFIN | ✅ Full | 17-Sep-2012 | 22-May-2026 | 34,740 | 1m 5m 30m 1d | 3,375 | 3,071 | 14,294 | 14,000 |
| 43 | SUNPHARMA | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 44 | TATAMOTORS | ⚠️ Partial | 12-Nov-2025 | 22-May-2026 | 18,341 | 1m 5m 30m 1d | 129 | 1,612 | 7,600 | 9,000 |
| 45 | TATASTEEL | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 46 | TCS | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 47 | TECHM | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 48 | TITAN | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d | 3,377 | 3,071 | 14,000 | 15,000 |
| 49 | TRENT | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |
| 50 | ULTRACEMCO | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,449 | 1m 5m 30m 1d | 3,378 | 3,071 | 14,000 | 15,000 |
| 51 | WIPRO | ✅ Full | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d | 3,389 | 3,227 | 15,130 | 18,000 |

**Legend:** ✅ Full = 13 years of data · ⚠️ Partial = limited history · ❌ Missing = not in DB

**Footnotes:**
1. **ETERNAL** — Zomato was renamed Eternal Ltd in Feb 2025. `ETERNAL` ticker has 1 year of data. `ZOMATO` (old ticker) is separately available with full history from Jul-2021. For backtesting pre-2025, use `ZOMATO`.
2. **HDFCLIFE / SBILIFE** — Listed via IPO. HDFCLIFE (Nov-2017), SBILIFE (May-2025 in DB — deeper backfill possible via older Breeze sessions).
3. **JIOFIN** — Listed Aug-2023 as a demerger from Reliance Industries. Full history available from listing date.
4. **LTIM** — LTIMindtree Ltd (NSE: LTIM) — the post-merger entity formed from L&T Infotech + Mindtree (Nov-2022) is **not present in Breeze's symbol master**. Historical data unavailable from this source.
5. **TATAMOTORS** — Only 6 months of data (Nov-2025 to May-2026). Needs backfill for full history.

### Nifty 50 Summary

| Category | Count |
|----------|-------|
| ✅ Full history (13+ years) | 43 |
| ✅ Since IPO / listing | 3 (HDFCLIFE, JIOFIN, ZOMATO/ETERNAL) |
| ⚠️ Partial data | 3 (ETERNAL, SBILIFE, TATAMOTORS) |
| ❌ Not available in Breeze | 1 (LTIM) |
| **Total** | **51** |

---

## Bank Nifty — Coverage Analysis

**Index composition:** 12 stocks · **10 available in DB** · 2 missing

> Bank Nifty (Nifty Bank Index) is composed of the 12 most liquid and large-cap banking stocks listed on NSE.

### Symbol-by-Symbol Status

| # | Symbol | Company | Status | Data From | Data To | Total Candles | Intervals |
|---|--------|---------|--------|-----------|---------|---------------|-----------|
| 1 | AUBANK | AU Small Finance Bank | ❌ Missing | — | — | — | — |
| 2 | AXISBANK | Axis Bank Ltd | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| 3 | BANDHANBNK | Bandhan Bank Ltd | ⚠️ 1d only | 28-May-2025 | 26-May-2026 | 247 | 1d only |
| 4 | BANKBARODA | Bank of Baroda | ✅ Full | 17-Sep-2012 | 22-May-2026 | 35,743 | 1m 5m 30m 1d |
| 5 | FEDERALBNK | Federal Bank Ltd | ✅ Full | 17-Sep-2012 | 22-May-2026 | 34,739 | 1m 5m 30m 1d |
| 6 | HDFCBANK | HDFC Bank Ltd | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| 7 | ICICIBANK | ICICI Bank Ltd | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| 8 | IDFCFIRSTB | IDFC First Bank Ltd | ✅ Since listing | 06-Nov-2015 | 22-May-2026 | 33,957 | 1m 5m 30m 1d |
| 9 | INDUSINDBK | IndusInd Bank Ltd | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| 10 | KOTAKBANK | Kotak Mahindra Bank | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| 11 | PNB | Punjab National Bank | ❌ Missing | — | — | — | — |
| 12 | SBIN | State Bank of India | ✅ Full | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |

### Bank Nifty Summary

| Category | Count |
|----------|-------|
| ✅ Full history | 8 |
| ✅ Since listing (IDFC merger Nov-2015) | 1 |
| ⚠️ Partial / daily only | 1 (BANDHANBNK) |
| ❌ Not in DB | 2 (AUBANK, PNB) |
| **Total** | **12** |

**Action required:**
- **AUBANK** (AU Small Finance Bank) — download needed. Breeze code: `AUBANK` (NSE)
- **PNB** (Punjab National Bank) — download needed. Breeze code: likely `PNBLIM` or `PNB` (NSE)
- **BANDHANBNK** — has only 1 year of 1d data. Upgrade to include 5m/30m/1m intraday

---

## Indices Available

All major tradeable indices with full intraday history:

| Symbol | Description | From | To | Candles | Intervals |
|--------|-------------|------|----|---------|-----------|
| NIFTY | Nifty 50 Index | 13-Sep-2012 | 26-May-2026 | 39,553 | 1m 5m 30m 1d |
| BANKNIFTY | Nifty Bank Index | 17-Sep-2012 | 22-May-2026 | 35,852 | 1m 5m 30m 1d |
| CNXIT | Nifty IT Index | 13-Sep-2012 | 26-May-2026 | 39,553 | 1m 5m 30m 1d |
| FINNIFTY | Nifty Financial Services | 28-May-2025 | 26-May-2026 | 31,322 | 1m 5m 30m 1d |
| MIDCPNIFTY | Nifty Midcap Select | 28-May-2025 | 26-May-2026 | 31,337 | 1m 5m 30m 1d |
| SENSEX | BSE Sensex | 28-May-2025 | 26-May-2026 | 31,314 | 1m 5m 30m 1d |
| NIFTYFINSERV | Nifty Financial Services | 17-Sep-2012 | 22-May-2026 | 35,819 | 1m 5m 30m 1d |
| NIFTYMIDCAP50 | Nifty Midcap 50 | 17-Sep-2012 | 22-May-2026 | 34,987 | 1m 5m 30m 1d |
| NIFTYMIDSELECT | Nifty Midcap Select | 15-Sep-2021 | 22-May-2026 | 33,619 | 1m 5m 30m 1d |
| NIFTYINFRA | Nifty Infrastructure | 17-Sep-2012 | 22-May-2026 | 35,582 | 1m 5m 30m 1d |
| NIFTYPSE | Nifty PSE | 17-Sep-2012 | 22-May-2026 | 34,987 | 1m 5m 30m 1d |
| NIFTYNEXT50 | Nifty Next 50 | 24-Apr-2024 | 22-May-2026 | 32,975 | 1m 5m 30m 1d |
| INDIAVIX | India VIX | 17-Sep-2012 | 22-May-2026 | 35,851 | 1m 5m 30m 1d |

> **Note:** FINNIFTY, MIDCPNIFTY, SENSEX history starts May-2025 — these were recently added and Breeze's historical feed for these begins at that point. NIFTYFINSERV / NIFTYMIDCAP50 are older equivalents covering back to 2012.

---

## Full DB Catalog — All 164 Symbols

### Indices (13)
| Symbol | Description | From | To | Candles |
|--------|-------------|------|----|---------|
| BANKNIFTY | Nifty Bank | 17-Sep-2012 | 22-May-2026 | 35,852 |
| CNXIT | Nifty IT | 13-Sep-2012 | 26-May-2026 | 39,553 |
| FINNIFTY | Nifty Financial Services | 28-May-2025 | 26-May-2026 | 31,322 |
| INDIAVIX | India VIX | 17-Sep-2012 | 22-May-2026 | 35,851 |
| MIDCPNIFTY | Nifty Midcap Select | 28-May-2025 | 26-May-2026 | 31,337 |
| NIFTY | Nifty 50 | 13-Sep-2012 | 26-May-2026 | 39,553 |
| NIFTYFINSERV | Nifty Fin Services | 17-Sep-2012 | 22-May-2026 | 35,819 |
| NIFTYINFRA | Nifty Infrastructure | 17-Sep-2012 | 22-May-2026 | 35,582 |
| NIFTYMIDCAP50 | Nifty Midcap 50 | 17-Sep-2012 | 22-May-2026 | 34,987 |
| NIFTYMIDSELECT | Nifty Midcap Select | 15-Sep-2021 | 22-May-2026 | 33,619 |
| NIFTYNEXT50 | Nifty Next 50 | 24-Apr-2024 | 22-May-2026 | 32,975 |
| NIFTYPSE | Nifty PSE | 17-Sep-2012 | 22-May-2026 | 34,987 |
| SENSEX | BSE Sensex | 28-May-2025 | 26-May-2026 | 31,314 |

### Nifty 50 Stocks (50 of 51)
| Symbol | From | To | Candles | Intervals |
|--------|------|----|---------|-----------|
| ADANIENT | 17-Sep-2012 | 22-May-2026 | 35,742 | 1m 5m 30m 1d |
| ADANIPORTS | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| APOLLOHOSP | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| ASIANPAINT | 14-Sep-2012 | 22-May-2026 | 35,449 | 1m 5m 30m 1d |
| AXISBANK | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BAJAJ-AUTO | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BAJAJFINSV | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BAJFINANCE | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BEL | 17-Sep-2012 | 22-May-2026 | 35,742 | 1m 5m 30m 1d |
| BHARTIARTL | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BPCL | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| BRITANNIA | 14-Sep-2012 | 22-May-2026 | 35,446 | 1m 5m 30m 1d |
| CIPLA | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| COALINDIA | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| DRREDDY | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| EICHERMOT | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| ETERNAL ¹ | 28-May-2025 | 26-May-2026 | 17,318 | 5m 30m 1d |
| GRASIM | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| HCLTECH | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| HDFCBANK | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| HDFCLIFE | 17-Nov-2017 | 22-May-2026 | 33,467 | 1m 5m 30m 1d |
| HEROMOTOCO | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| HINDALCO | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| HINDUNILVR | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| ICICIBANK | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| INDUSINDBK | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| INFY | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| ITC | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| JIOFIN | 21-Aug-2023 | 26-May-2026 | 37,042 | 1m 5m 30m 1d |
| JSWSTEEL | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| KOTAKBANK | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| LT | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| MARUTI | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| NESTLEIND | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| NTPC | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| ONGC | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| POWERGRID | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| RELIANCE | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| SBIN | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| SBILIFE | 28-May-2025 | 26-May-2026 | 17,318 | 5m 30m 1d |
| SHRIRAMFIN | 17-Sep-2012 | 22-May-2026 | 34,740 | 1m 5m 30m 1d |
| SUNPHARMA | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| TATAMOTORS ⁵ | 12-Nov-2025 | 22-May-2026 | 18,341 | 1m 5m 30m 1d |
| TATASTEEL | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| TCS | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| TECHM | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| TITAN | 14-Sep-2012 | 22-May-2026 | 35,448 | 1m 5m 30m 1d |
| TRENT | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| ULTRACEMCO | 14-Sep-2012 | 22-May-2026 | 35,449 | 1m 5m 30m 1d |
| WIPRO | 13-Sep-2012 | 26-May-2026 | 39,746 | 1m 5m 30m 1d |
| **LTIM** | ❌ NOT AVAILABLE | — | — | — |

### Additional Stocks in DB (101 more)
*Includes Nifty Next 50, Adani Group, Insurance, Mid-cap, and sector leaders*

| Symbol | From | To | Candles | Tier |
|--------|------|----|---------|------|
| ABB | 17-Sep-2012 | 22-May-2026 | 35,742 | Next50 |
| ABCAPITAL | 28-May-2025 | 26-May-2026 | 247 | Additional |
| ABFRL | 28-May-2025 | 26-May-2026 | 247 | Additional |
| ADANIGREEN | 18-Jun-2018 | 22-May-2026 | 34,323 | Adani Group |
| ADANIPOWER | 17-Sep-2012 | 22-May-2026 | 35,742 | Adani Group |
| ADANITRANS | 28-May-2025 | 26-May-2026 | 3,318 | Next50 |
| ALKEM | 28-May-2025 | 26-May-2026 | 247 | Additional |
| AMBUJACEM | 17-Sep-2012 | 22-May-2026 | 35,742 | Next50 |
| ATGL | 05-Nov-2018 | 22-May-2026 | 34,230 | Adani Group |
| AUROPHARMA | 28-May-2025 | 26-May-2026 | 3,318 | Next50 |
| BAJAJHFL | 16-Sep-2024 | 22-May-2026 | 32,780 | Financial |
| BALKRISIND | 28-May-2025 | 26-May-2026 | 247 | Additional |
| BANDHANBNK | 28-May-2025 | 26-May-2026 | 247 | Bank Nifty |
| BANKBARODA | 17-Sep-2012 | 22-May-2026 | 35,743 | Bank Nifty |
| BATAINDIA | 28-May-2025 | 26-May-2026 | 247 | Additional |
| BERGEPAINT | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| BHEL | 17-Sep-2012 | 22-May-2026 | 35,742 | Next50 |
| BIOCON | 13-Sep-2012 | 26-May-2026 | 6,616 | Next50 (partial) |
| BOSCHLTD | 17-Sep-2012 | 22-May-2026 | 35,742 | Next50 |
| CANBK | 17-Sep-2012 | 22-May-2026 | 34,743 | Next50 |
| CHOLAFIN | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| CNXIT | 13-Sep-2012 | 26-May-2026 | 39,553 | Index |
| COFORGE | 17-Sep-2012 | 22-May-2026 | 34,725 | IT Mid |
| COLPAL | 13-Sep-2012 | 26-May-2026 | 39,669 | FMCG |
| CONCOR | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| DABUR | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| DEEPAKNTR | 28-May-2025 | 26-May-2026 | 247 | Additional |
| DIVISLAB | 14-Sep-2012 | 22-May-2026 | 35,448 | Pharma |
| DLF | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| DMART | 21-Mar-2017 | 22-May-2026 | 33,631 | Next50 |
| ETERNAL | 28-May-2025 | 26-May-2026 | 17,318 | Nifty50 (renamed) |
| EXIDEIND | 28-May-2025 | 26-May-2026 | 247 | Additional |
| FEDERALBNK | 17-Sep-2012 | 22-May-2026 | 34,739 | Bank Nifty |
| GAIL | 13-Sep-2012 | 26-May-2026 | 34,460 | PSU Energy |
| GODREJCP | 17-Sep-2012 | 22-May-2026 | 34,742 | FMCG |
| GODREJPROP | 17-Sep-2012 | 22-May-2026 | 34,742 | Real Estate |
| HAL | 28-May-2025 | 26-May-2026 | 3,318 | Next50 |
| HAVELLS | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| HINDPETRO | 17-Sep-2012 | 22-May-2026 | 34,742 | PSU |
| HINDZINC | 17-Sep-2012 | 22-May-2026 | 34,742 | Mining |
| ICICIGI | 27-Sep-2017 | 22-May-2026 | 33,502 | Insurance |
| ICICIPRULI | 29-Sep-2016 | 22-May-2026 | 33,748 | Insurance |
| IDFCFIRSTB | 06-Nov-2015 | 22-May-2026 | 33,957 | Bank Nifty |
| INDIANB | 28-May-2025 | 26-May-2026 | 247 | Additional |
| INDUSTOWER | 28-May-2025 | 26-May-2026 | 3,318 | Next50 |
| IOC | 17-Sep-2012 | 22-May-2026 | 34,742 | PSU |
| IRCTC | 14-Oct-2019 | 22-May-2026 | 33,002 | PSU |
| JINDALSTEL | 17-Sep-2012 | 22-May-2026 | 34,742 | Next50 |
| JUBLFOOD | 28-May-2025 | 26-May-2026 | 247 | Additional |
| KAJARIACER | 28-May-2025 | 26-May-2026 | 247 | Additional |
| KANSAINER | 28-May-2025 | 26-May-2026 | 247 | Additional |
| KPIT | 22-Apr-2019 | 22-May-2026 | 33,117 | IT Mid |
| LALPATHLAB | 28-May-2025 | 26-May-2026 | 247 | Additional |
| LICI | 28-May-2025 | 26-May-2026 | 247 | Additional |
| LODHA | 28-May-2025 | 26-May-2026 | 3,318 | Next50 |
| LTTS | 23-Sep-2016 | 22-May-2026 | 33,752 | IT |
| LUPIN | 13-Sep-2012 | 26-May-2026 | 39,669 | Pharma |
| M&M | 14-Sep-2012 | 22-May-2026 | 35,448 | Auto |
| MANAPPURAM | 17-Sep-2012 | 22-May-2026 | 34,742 | NBFC |
| MARICO | 17-Sep-2012 | 22-May-2026 | 34,742 | FMCG |
| MAXHEALTH | 28-May-2025 | 26-May-2026 | 247 | Additional |
| MCDOWELL-N | 17-Sep-2012 | 22-May-2026 | 34,742 | FMCG |
| MFSL | 28-May-2025 | 26-May-2026 | 247 | Additional |
| MOIL | 17-Sep-2012 | 22-May-2026 | 34,742 | Mining |
| MOTHERSON | 17-Sep-2012 | 22-May-2026 | 34,741 | Auto Ancillary |
| MPHASIS | 17-Sep-2012 | 22-May-2026 | 34,742 | IT |
| MRF | 28-May-2025 | 26-May-2026 | 247 | Additional |
| MUTHOOTFIN | 17-Sep-2012 | 22-May-2026 | 34,742 | NBFC |
| NATIONALUM | 28-May-2025 | 26-May-2026 | 247 | Additional |
| NAUKRI | 17-Sep-2012 | 22-May-2026 | 34,742 | Internet |
| NHPC | 17-Sep-2012 | 22-May-2026 | 34,742 | PSU Hydro |
| NMDC | 17-Sep-2012 | 22-May-2026 | 34,742 | Mining |
| NYKAA | 28-May-2025 | 26-May-2026 | 247 | Additional |
| OBEROIRLTY | 17-Sep-2012 | 22-May-2026 | 34,742 | Real Estate |
| OFSS | 28-May-2025 | 26-May-2026 | 3,318 | IT |
| PAGEIND | 28-May-2025 | 26-May-2026 | 3,318 | FMCG |
| PERSISTENT | 17-Sep-2012 | 22-May-2026 | 34,742 | IT |
| PFC | 28-May-2025 | 26-May-2026 | 247 | PSU Finance |
| PIDILITIND | 17-Sep-2012 | 22-May-2026 | 34,742 | Chemicals |
| PIIND | 13-Sep-2012 | 26-May-2026 | 6,616 | Agri (partial) |
| POLICYBZR | 28-May-2025 | 26-May-2026 | 247 | Insurtech |
| PRESTIGE | 17-Sep-2012 | 22-May-2026 | 34,742 | Real Estate |
| RADICO | 17-Sep-2012 | 22-May-2026 | 34,742 | FMCG |
| RECLTD | 17-Sep-2012 | 22-May-2026 | 34,742 | PSU Finance |
| SAIL | 17-Sep-2012 | 22-May-2026 | 34,743 | PSU Steel |
| SBILIFE | 28-May-2025 | 26-May-2026 | 17,318 | Insurance |
| SIEMENS | 17-Sep-2012 | 22-May-2026 | 34,742 | Capital Goods |
| SRF | 17-Sep-2012 | 22-May-2026 | 34,742 | Chemicals |
| SYNGENE | 28-May-2025 | 26-May-2026 | 247 | Pharma |
| TATACHEM | 28-May-2025 | 26-May-2026 | 3,318 | Chemicals |
| TATACOMM | 17-Sep-2012 | 22-May-2026 | 34,742 | Telecom |
| TATACONSUM | 28-May-2025 | 26-May-2026 | 3,318 | FMCG |
| TATAPOWER | 17-Sep-2012 | 22-May-2026 | 34,742 | Power |
| TORNTPHARM | 17-Sep-2012 | 22-May-2026 | 34,742 | Pharma |
| TORNTPOWER | 28-May-2025 | 26-May-2026 | 3,318 | Power |
| TVSMOTOR | 17-Sep-2012 | 22-May-2026 | 34,742 | Auto |
| UPL | 17-Sep-2012 | 22-May-2026 | 34,741 | Agri |
| VBL | 08-Nov-2016 | 22-May-2026 | 33,722 | FMCG |
| VEDL | 17-Sep-2012 | 22-May-2026 | 34,736 | Mining |
| VOLTAS | 17-Sep-2012 | 22-May-2026 | 34,742 | Industrials |
| YESBANK | 28-May-2025 | 26-May-2026 | 247 | Private Bank |
| ZOMATO | 23-Jul-2021 | 22-May-2026 | 32,559 | Internet (old ticker) |
| ZYDUSLIFE | 17-Sep-2012 | 22-May-2026 | 34,741 | Pharma |

---

## Action Items / Gaps to Address

| Priority | Symbol | Issue | Action |
|----------|--------|-------|--------|
| 🔴 High | **TATAMOTORS** | Only 6 months of data (Nifty 50 stock) | Re-download with `--days 3000` |
| 🔴 High | **AUBANK** | Bank Nifty constituent — not in DB at all | Run: `download_mapped.py --symbols AUBANK` |
| 🔴 High | **PNB** | Bank Nifty constituent — not in DB at all | Find Breeze code, then download |
| 🟡 Medium | **BANDHANBNK** | Only 1d data, 1 year — needs intraday | Re-download as nifty50 tier (5m/30m/1m) |
| 🟡 Medium | **SBILIFE** | Only 1 year, no 1m — Nifty 50 stock | Re-download with deeper history |
| 🟡 Medium | **ETERNAL** | Only 1 year, no 1m — use ZOMATO pre-Feb-2025 | Run `download_chains.py` during market hours |
| 🟢 Low | **LTIM** | Not in Breeze master file at all | Check alternate data source (NSE data API) |
| 🟢 Low | **FINNIFTY/SENSEX/MIDCPNIFTY** | Only 1 year of history | Breeze historical limit for these indices |

---

## Data Intervals Reference

| Interval | DB Key | Use Case | Max Candles/Symbol |
|----------|--------|----------|-------------------|
| 1-minute | `1m` | Scalping, tick analysis | ~16,000 (45 trading days) |
| 5-minute | `5m` | Intraday strategies | ~15,000 (200 trading days) |
| 30-minute | `30m` | Swing, options | ~3,200 (250 trading days) |
| 1-day | `1d` | Long-term, multi-year | ~3,400 (13.5 years) |

---

*Report generated by Algotime data pipeline · Data source: ICICI Breeze Connect API · All times IST*
