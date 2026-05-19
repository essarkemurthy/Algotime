# Algo Trade Dashboard

A real-time algorithmic trading dashboard for Indian markets, built on ICICI Direct's **Breeze Connect** API. Stream live prices, view interactive charts with technical indicators, build multi-leg option strategies, run automated signal generators, and simulate fully automated paper trading — all from a single browser-based interface.

**No PostgreSQL required to get started.** The app runs entirely in-memory out of the box; PostgreSQL is optional but unlocks historical charting, EOD data persistence, and backtesting.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Environment File (.env) — Full Reference](#environment-file-env--full-reference)
5. [Getting Breeze Credentials](#getting-breeze-credentials)
6. [Daily Session Token Renewal](#daily-session-token-renewal)
7. [Getting the Security Master File](#getting-the-security-master-file)
8. [Starting the App](#starting-the-app)
9. [Pre-Trading Session Checklist](#pre-trading-session-checklist)
10. [Dos and Don'ts — Paper Trading](#dos-and-donts--paper-trading)
11. [Automated Algo Paper Trading](#automated-algo-paper-trading)
12. [Pages & Navigation](#pages--navigation)
13. [Paper Trading — Manual Orders](#paper-trading--manual-orders)
14. [Option Strategy Builder](#option-strategy-builder)
15. [Strategy Signal Generators](#strategy-signal-generators)
16. [Charts & Technical Analysis](#charts--technical-analysis)
17. [PostgreSQL Setup (Optional)](#postgresql-setup-optional)
18. [Historical Data Download](#historical-data-download)
19. [NSE Bulk Download (No Breeze Required)](#nse-bulk-download-no-breeze-required)
20. [Database Schema](#database-schema)
21. [Project Structure](#project-structure)
22. [API Reference](#api-reference)
23. [Troubleshooting](#troubleshooting)
24. [Disclaimer](#disclaimer)

---

## Features

| Area | What it does |
|---|---|
| **Live Prices** | WebSocket stream of LTP, volume, bid/ask from Breeze Connect — auto-subscribed for all watchlist symbols at 9:15 IST |
| **Automated Algo Paper Trading** | Toggle ON any strategy → signals fire automatically → paper orders placed with calculated SL / T1 / T2 → auto-squared off at targets or 15:20 IST EOD |
| **Stock-level Trade Lock** | Once any strategy enters a trade on a stock, all other strategies stop signalling for that stock until the trade closes |
| **Simulated Breeze Call Monitor** | Counts every order/exit that WOULD hit Breeze in live mode — helps you estimate real API quota usage before going live |
| **Option Chain** | Full chain snapshot with Delta, Gamma, Theta, Vega, IV per strike |
| **Interactive Charts** | Candlestick / bar / line with EMA 9/21/50, Bollinger Bands, VWAP, RSI, MACD |
| **Option Strategy Builder** | One-click multi-leg strategies: Iron Condor, Bull Call Spread, Bear Put Spread, Covered Call, Long Straddle |
| **Strategy Alerts** | Auto-fires profit target / stop-loss alerts (50% profit / 2× SL for credit; 80% profit / 50% SL for debit) |
| **Intraday Signal Monitor** | 5 equity + 3 options strategies scanned every 15 seconds during market hours |
| **Signal Generators** | 5 automated strategies: 0DTE Scalper, IVR Iron Condor, VIX Regime Switcher, Gamma Scalper, Momentum Breakout |
| **Rate Limiter** | Thread-safe sliding-window limiter (75 calls/min, 4,500 calls/day) prevents Breeze API bans |
| **Data Collection** | Persists spot ticks, candles, futures, option chain snapshots, PCR, IV rank to PostgreSQL |
| **NSE Bulk Download** | Downloads 2 years of Nifty 50 equity / futures / options EOD — no Breeze credentials needed |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10 or later** | 3.11 recommended |
| **ICICI Direct account** | With Breeze API access enabled — [api.icicidirect.com](https://api.icicidirect.com/) |
| **PostgreSQL 14+** | **Optional** — only needed for historical charts and data persistence |

---

## Installation

```powershell
# 1. Clone the repository
git clone https://github.com/Techultime/algo-trade.git
cd algo-trade

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

> **PowerShell execution policy:** If step 3 fails, run once as Administrator:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

## Environment File (.env) — Full Reference

Create your `.env` file in the project root (copy from `.env.example`):

```powershell
copy .env.example .env
```

Then edit it with the values below:

```ini
# ── Breeze API (ICICI Direct) ─────────────────────────────────────────────────
# Permanent — copy once from api.icicidirect.com → My Apps
BREEZE_API_KEY=your_api_key_here
BREEZE_API_SECRET=your_api_secret_here

# Expires daily — generate a fresh token every morning before 9:00 AM
# Steps: api.icicidirect.com → Login → click the session URL → copy apisession value
BREEZE_SESSION_TOKEN=your_session_token_here

# ── PostgreSQL (Optional) ─────────────────────────────────────────────────────
# Leave blank to run fully in-memory (paper trading still works without a DB)
DB_URL=postgresql://postgres:your_password@localhost:5432/trading_data
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=trading_data

# ── AI Morning Brief (Optional) ───────────────────────────────────────────────
# Leave blank to disable. Needs: pip install anthropic
ANTHROPIC_API_KEY=

# ── Safety Gate ───────────────────────────────────────────────────────────────
# NEVER set this to true unless you intend to place REAL orders via Breeze.
# Paper trading works with LIVE_TRADING=false (the default).
LIVE_TRADING=false

# ── Tuning (Optional) ─────────────────────────────────────────────────────────
# How often the intraday monitor scans all watchlist strategies (seconds)
# Default: 15. Lower = more responsive signals; higher = less CPU/DB load.
INTRADAY_SCAN_SEC=15
```

> **The `.env` file is listed in `.gitignore` and will never be committed to git.**

---

## Getting Breeze Credentials

You need three values from ICICI Direct. The first two are **permanent**; the third changes every day.

### Step 1 — Enable API access on your account

1. Log in to your ICICI Direct account at [icicidirect.com](https://www.icicidirect.com/)
2. Go to **Profile → API Access** and enable it (one-time activation, may require a call to support)

### Step 2 — Create an app and get API Key + Secret (one-time)

1. Go to [api.icicidirect.com](https://api.icicidirect.com/) and log in with your ICICI Direct credentials
2. Click **My Apps → Create New App**
3. Fill in any app name (e.g. "Algo Trade") and redirect URL (e.g. `http://localhost:8000`)
4. After creation, copy the **API Key** and **API Secret** shown on the app details page
5. Paste them into `.env`:
   ```ini
   BREEZE_API_KEY=your_api_key_here
   BREEZE_API_SECRET=your_api_secret_here
   ```
   These values are permanent — you only do this once.

---

## Daily Session Token Renewal

> **The session token expires every day and must be refreshed each morning before starting the app.**

### How to get a fresh token (do this before 9:00 AM every trading day)

1. Open a browser and go to:
   ```
   https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY
   ```
   Replace `YOUR_API_KEY` with the value from `.env`.

2. Log in with your ICICI Direct credentials (user ID + password + OTP).

3. After successful login you are redirected to your app's redirect URL. The URL will look like:
   ```
   http://localhost:8000/?apisession=55685908&status=...
   ```

4. Copy the value after `apisession=` — that is your **session token** for today.

5. Open `.env` and update:
   ```ini
   BREEZE_SESSION_TOKEN=55685908
   ```

6. **Save the file.** Start or restart the app (see [Starting the App](#starting-the-app)).

> **Tip:** You can also enter the token directly in the dashboard's connection wizard without editing `.env` — useful if the app is already running.

---

## Getting the Security Master File

The security master maps stock names to internal Breeze tokens needed for WebSocket subscriptions. It is downloaded automatically.

### Automatic download (recommended)

The app downloads the security master from ICICI Direct every morning at **8:30 IST** automatically — no manual action needed.

To trigger a manual download at any time while the app is running:

```powershell
# From PowerShell (app must be running)
Invoke-RestMethod -Method POST http://localhost:8000/api/security-master/download
```

Or via curl:
```cmd
curl -X POST http://localhost:8000/api/security-master/download
```

### Manual download (if needed)

If the app cannot reach ICICI Direct at startup, download the master file manually:

1. Log in to [api.icicidirect.com](https://api.icicidirect.com/)
2. Go to **Downloads → Security Master**
3. Download the latest CSV file
4. Place it in the project root as `security_master.csv`
5. The app will load it automatically on next start

### What it's used for

The security master is required to:
- Subscribe live WebSocket feeds for individual stocks
- Resolve stock codes to NFO option/futures contract tokens
- Validate symbol names before placing orders

> Without a security master, the app still works for NIFTY, BANKNIFTY, and the default watchlist symbols — it falls back to hardcoded token mappings for these.

---

## Starting the App

### Normal start (production)

```powershell
# Activate the virtual environment
.venv\Scripts\Activate.ps1

# Start the server (no auto-reload — stable for trading sessions)
python app.py
```

The app starts on **http://localhost:8000** by default.

### Alternative: uvicorn directly

```powershell
uvicorn app:app --host 0.0.0.0 --port 8000
```

> **Important:** Always use a single worker (the default). Paper trading state and the LTP cache are in-memory — multiple workers would give each browser tab an independent state.

### Verify it started correctly

You should see log lines like:
```
INFO:     Application startup complete.
INFO:     Intraday monitor loop started (scan every 15 s).
INFO:     Paper monitor loop started.
INFO:     Strategy signal loop started.
```

If you see a PostgreSQL error — that is normal if DB is not configured. The app continues in in-memory mode.

### Stop the app

Press `Ctrl + C` in the terminal. All in-memory state (paper positions, orders, LTP cache) is lost on stop — this is expected.

---

## Pre-Trading Session Checklist

Run through this list **every morning before 9:15 IST**.

### 8:00 AM — Credentials

- [ ] **Renew session token** — log in at `api.icicidirect.com`, get fresh `apisession` value
- [ ] **Update `.env`** — paste new token as `BREEZE_SESSION_TOKEN=...`
- [ ] Verify `LIVE_TRADING=false` in `.env` (must be false for paper trading)

### 8:30 AM — Start the app

- [ ] Activate virtual environment: `.venv\Scripts\Activate.ps1`
- [ ] Start app: `python app.py`
- [ ] Confirm no import errors in the terminal
- [ ] Open browser: `http://localhost:8000`

### 8:45 AM — Connect Breeze

- [ ] Go to the **Live Dashboard** (`http://localhost:8000`)
- [ ] Enter API Key, API Secret, Session Token in the connection wizard
- [ ] Click **Connect to Breeze** — status dot should turn green
- [ ] Confirm live prices appear in the LTP strip at the top

### 8:50 AM — Verify data feeds

- [ ] Navigate to **Paper Trading** (`http://localhost:8000/paper`)
- [ ] Confirm the strategy cards load (equity + options sections visible)
- [ ] Watchlist symbols show LTP values (NIFTY, CNXBAN, RELIND, HDFCBANK, TCS)
- [ ] Check the **Simulated Breeze API calls** panel shows `0 calls` (reset from last session)

### 9:00 AM — Arm strategies

- [ ] In the **Equity Strategies** section, toggle ON the strategies you want active (toggle turns teal)
- [ ] In the **Options Strategies** section, toggle ON any options strategies you want to run
- [ ] Confirm toggled strategies show **Armed** pill (not Paused)
- [ ] Leave strategies you do NOT want to auto-trade toggled OFF

### 9:14:50 AM — Auto-subscription kicks in

- [ ] App auto-subscribes all 5 watchlist symbols to Breeze WebSocket
- [ ] LTP cache warms up with live prices
- [ ] Terminal log shows: `Watchlist WS subscriptions refreshed (5 symbols)`

### 9:15 AM — Market open

- [ ] Intraday monitor begins scanning every 15 seconds
- [ ] Options strategies begin polling every 10 seconds
- [ ] First signals will appear within 1–2 scan cycles
- [ ] Confirm orders start appearing in the Order Book when signals fire
- [ ] Monitor the **Simulated Breeze API calls** panel — counters should increment

### During trading hours

- [ ] Check **Open Positions** for active trades with SL / T1 / T2 levels set
- [ ] Monitor the **Signal Feed** for new signals
- [ ] Watch for T1 / T2 / SL auto-exit notifications in the browser

### 15:20 IST — EOD square-off

- [ ] All open paper positions are automatically squared off at 15:20 IST
- [ ] Confirm all positions show as closed in the positions panel

### After market close

- [ ] Review **Realised P&L** and **Order Log** for the day
- [ ] Note total **Simulated Breeze API calls** — this is your live trading call budget estimate
- [ ] Stop the app: `Ctrl + C`

---

## Dos and Don'ts — Paper Trading

### ✅ Dos

**Before the session:**
- Do renew the Breeze session token every morning — a stale token means no live data
- Do check `LIVE_TRADING=false` in `.env` every single time before starting
- Do start the app at least 30 minutes before market open so Breeze can connect and LTP cache can warm up
- Do verify that strategy toggles are in the correct ON/OFF state before 9:15 — armed strategies execute automatically without further input
- Do keep only 2–3 strategies armed at a time during initial testing to understand the behaviour

**During the session:**
- Do monitor the **Simulated Breeze API calls** panel to build intuition for real quota usage
- Do check that open positions have SL, T1, T2 levels shown — if any position has no SL, exit it manually
- Do watch the terminal logs (`log.info` lines) to verify auto-trade and auto-exit events are firing
- Do keep one browser tab on the paper trading page throughout the session

**After the session:**
- Do note which strategies generated the most signals vs acted trades — a ratio > 5:1 means the signal quality needs review
- Do compare simulated Breeze API calls to the daily limit (4,500/day) before considering live trading

### ❌ Don'ts

**Safety critical:**
- **Don't set `LIVE_TRADING=true`** unless you explicitly intend to place real orders with real money — there is no confirmation prompt
- **Don't run multiple instances** of the app simultaneously — they share no state, and you will have two independent paper books
- **Don't close the terminal** running the app while a trading session is active — the app and all in-memory state will be lost
- **Don't use `--reload`** flag with uvicorn during a live session — a file change would restart the app and wipe all positions

**Strategy behaviour:**
- **Don't arm all 10 strategies simultaneously** on first use — start with 1–2 and confirm orders fire correctly before scaling up
- **Don't manually place paper orders on a stock that has an algo position open** — the algo lock (stock-level trade lock) only checks for auto-placed positions, not manual ones
- **Don't assume signals = trades** — signals are generated only when conditions are met; on low-volatility days many signals will fire as WAIT / NO_DATA

**Data and credentials:**
- **Don't commit `.env` to git** — API keys and passwords are in that file
- **Don't share your session token** — it gives full API access to your ICICI Direct account
- **Don't run the app without the venv activated** — system Python may have incompatible package versions

---

## Automated Algo Paper Trading

This is the core feature — strategies run continuously, generate signals, place paper trades automatically, and exit them without human intervention.

### How it works end-to-end

```
9:14:50 IST
  └─ App auto-subscribes NIFTY, CNXBAN, RELIND, HDFCBANK, TCS to Breeze WebSocket

9:15 IST — Market opens
  └─ Intraday monitor starts scanning every 15 seconds
  └─ Options strategies poll every 10 seconds

Every 15 s (intraday) / 10 s (options):
  └─ Strategy evaluates all watchlist symbols
  └─ If signal = LONG / SHORT and stock has no open position:
      └─ Paper order placed with calculated entry price
      └─ SL, T1, T2 price levels set automatically
      └─ ALL other strategies stop monitoring this stock

Every 3 s (paper monitor):
  └─ Checks each open position against its SL / T1 / T2
  └─ T1 hit → sell 1/3 qty, move SL to breakeven
  └─ T2 hit → sell 1/3 qty, move SL to T1 (lock-in)
  └─ SL hit → close full remaining position
  └─ Simulated Breeze call counter increments for each exit

15:20 IST — EOD square-off
  └─ All remaining open positions closed at live price
  └─ Trading halted for the day
```

### Auto-trade price levels

| Type | Equity (intraday) | Options (premium) |
|---|---|---|
| **Stop-Loss** | −0.8% from entry | −35% of premium |
| **Target 1** | +1.2% from entry | +25% of premium |
| **Target 2** | +2.0% from entry | +50% of premium |
| **T1 exit qty** | 1/3 of position | 1/3 of lots |
| **T2 exit qty** | 1/3 of position | 1/3 of lots |
| **Trailing SL** | 0.4% trail after T2 | 0.4% trail after T2 |

### Position sizing

Equity trades use fixed-fractional sizing:
- Capital slot: 10% of available cash
- Risk per trade: 1.5% of slot (max ₹2,500)
- Quantity = risk ÷ (entry − SL)

Options trades:
- Capital slot: 5% of available cash
- Risk per trade: 2% of slot (max ₹2,000)
- Quantity rounded to nearest lot size (75 for NIFTY)

### Stock-level trade lock

Once any strategy fires a trade on a stock, **all five strategies stop signalling for that stock** until the position is fully closed. This prevents duplicate entries and conflicting directions. The lock releases automatically when the position closes (SL, T1 full exit, T2 full exit, or EOD).

### Toggling strategies

On the Paper Trading page:
- **Toggle OFF (grey)** — strategy is paused, generates no signals, places no trades
- **Toggle ON (teal)** — strategy is Armed, auto-executes paper trades when signal fires
- The **pill badge** shows: `Armed` (on, no position), `In trade` (active position), or `Paused` (off)

### Simulated Breeze call counter

The panel at the bottom of the strategy section shows:

| Counter | Meaning in live trading |
|---|---|
| Orders placed | `place_order` calls to Breeze |
| T1 exits | Partial `place_order` (sell) calls |
| T2 exits | Partial `place_order` (sell) calls |
| SL exits | Full exit `place_order` calls |
| EOD square-offs | EOD `place_order` calls |
| Daily cap exits | Forced-exit `place_order` calls |

Use this to verify you stay within the 4,500 calls/day Breeze limit before going live.

---

## Pages & Navigation

| URL | Page | Description |
|---|---|---|
| `/` | **Live Dashboard** | Breeze connection wizard, live option chain, watchlist, LTP ticker |
| `/charts` | **Charts** | Interactive OHLCV charts with technical indicators and symbol watchlist |
| `/paper` | **Paper Trading** | Simulated order placement, portfolio tracker, algo strategy runner, signal feeds |
| `/strategies` | **Strategy Signals** | Automated signal generators with real-time signal log |

---

## Paper Trading — Manual Orders

The paper trading simulator (`/paper`) lets you trade with zero risk.

### Placing a single order

1. Enter a stock code (e.g. `NIFTY`, `INFY`, `SBIN`)
2. Choose Exchange (`NSE` for equities, `NFO` for derivatives)
3. Choose Product: **Cash / Equity** or **Options**
4. For options: select Right (CE / PE), Strike, and Expiry
5. Choose Action (BUY / SELL), Quantity, Order Type (Market / Limit)
6. Click **Place Paper Order**

Market orders fill at the live LTP. Limit orders fill instantly at the specified price.

### Portfolio summary

| Tile | What it shows |
|---|---|
| Starting Capital | Configurable — click Change to reset |
| Cash Available | Undeployed capital |
| Invested | Market value of open positions |
| Unrealised P&L | Live mark-to-market on open positions |
| Realised P&L | Cumulative closed-trade P&L |
| Total Return % | Combined return as % of starting capital |

---

## Option Strategy Builder

One-click multi-leg option strategies with automatic strike selection and break-even calculation.

| Strategy | Legs | Net | Outlook |
|---|---|---|---|
| **Iron Condor** | 4 | Credit | Neutral — range-bound market |
| **Bull Call Spread** | 2 | Debit | Mildly bullish |
| **Bear Put Spread** | 2 | Debit | Mildly bearish |
| **Covered Call** | 2 | Income | Hold futures, generate premium |
| **Long Straddle** | 2 | Debit | High volatility in either direction |

### Strike and lot size reference

| Symbol | Strike Step | Lot Size |
|---|---|---|
| NIFTY | 50 | 75 |
| BANKNIFTY | 100 | 30 |
| FINNIFTY | 50 | 40 |
| MIDCPNIFTY | 25 | 50 |
| RELIANCE | 50 | 250 |
| TCS | 50 | 150 |
| HDFCBANK | 10 | 550 |
| INFY | 20 | 300 |
| SBIN | 5 | 1500 |

---

## Strategy Signal Generators

### Equity intraday strategies (scanned every 15 s, 9:15–15:30 IST)

| Strategy ID | Name | Signal logic |
|---|---|---|
| `orb` | Opening Range Breakout | Price breaks 15m high/low with ATR stop |
| `vwap` | VWAP Reversal | Mean-reversion on >1.5σ deviation from VWAP |
| `ema_cross` | 9/21 EMA Crossover | 9-EMA crosses 21-EMA on 5m with volume filter |
| `sr_reversal` | S&R Reversal | Price rejects key support/resistance + reversal candle |
| `gap_go` | Gap & Go | Gap ≥1.5% from prev close with follow-through |

### Options / index strategies (polled every 10 s)

| Strategy ID | Name | Signal logic |
|---|---|---|
| `zero_dte` | 0DTE Expiry Scalper | VWAP + ORB breakout on expiry day; signals BUY_CALL / BUY_PUT |
| `ivr_condor` | IVR Iron Condor | IV Rank > 50% → ENTER_IRON_CONDOR; IVR < 30 → CLOSE |
| `vix_regime` | VIX Regime Switcher | VIX < 13 → sell, 13–18 → condor, > 18 → buy straddle |
| `gamma_scalp` | Gamma Scalper | Long ATM straddle + delta-neutral futures hedge |
| `momentum` | Momentum Breakout | N-period high/low break on 15m chart |

---

## Charts & Technical Analysis

### Timeframes

| Label | Interval | Data source |
|---|---|---|
| 1m | 1 minute | Live WebSocket ticks or DB |
| 5m | 5 minutes | Live WebSocket ticks or DB |
| 30m | 30 minutes | Live WebSocket ticks or DB |
| 1D | Daily | NSE Bulk Download or Breeze backfill → DB |

### Indicators

**Overlay:** EMA 9, EMA 21, EMA 50, Bollinger Bands (20, 2σ), VWAP

**Sub-charts:** Volume histogram, RSI (14), MACD (12/26/9)

---

## PostgreSQL Setup (Optional)

### 1. Install PostgreSQL

Download from [postgresql.org/download](https://www.postgresql.org/download/) (port 5432 default).

### 2. Start the service

```powershell
# Windows
Start-Service postgresql-x64-17
```

### 3. Create the database

```powershell
& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres -h localhost trading_data
```

### 4. Set DB_URL in `.env`

```ini
DB_URL=postgresql://postgres:your_password@localhost:5432/trading_data
```

Tables are created automatically on first start. No manual schema setup needed.

### 5. Recommended performance settings (run once in psql)

```sql
ALTER SYSTEM SET synchronous_commit          = 'off';
ALTER SYSTEM SET wal_buffers                 = '16MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET work_mem                    = '16MB';
SELECT pg_reload_conf();
```

---

## Historical Data Download

### Breeze REST API — data availability

| Interval | Equity (NSE) | Futures & Options (NFO) |
|---|---|---|
| 1m, 5m, 15m, 30m, 1D | 10 years | 3 years |

### Trigger via API

```cmd
curl -X POST http://localhost:8000/api/data/download ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\": [\"NIFTY\"]}"
```

---

## NSE Bulk Download (No Breeze Required)

Downloads 2 years of Nifty 50 + Sensex 30 EOD data directly from NSE bhavcopy archives. No credentials needed.

```cmd
curl -X POST http://localhost:8000/api/data/nse_bulk ^
  -H "Content-Type: application/json" ^
  -d "{\"days\": 730}"
```

Monitor progress:
```cmd
curl http://localhost:8000/api/data/status
```

---

## Database Schema

| Table | Contents |
|---|---|
| `candles` | OHLCV at 1m / 5m / 30m / 1d |
| `spot_ticks` | Every WebSocket LTP tick |
| `futures_ticks` | Futures LTP and open interest |
| `futures_candles` | Futures OHLCV |
| `options_eod` | Options OHLCV + OI + Greeks per strike per day |
| `chain_snapshots` | Full option chain every 5 minutes |
| `depth_snapshots` | 5-level market depth |
| `pcr_snapshots` | Put-Call Ratio per expiry |
| `iv_daily` | Daily ATM IV summary for IV Rank / IV Percentile |

---

## Project Structure

```
algo-trade/
│
├── app.py                      # FastAPI server — all HTTP + WebSocket routes
├── paper_engine.py             # In-memory paper trading engine (IST-aware EOD)
├── options_engine.py           # Breeze session + option chain utilities
│
├── trade_engine/
│   ├── strategy_signals.py     # 5 automated options signal generators
│   ├── option_strategies.py    # Multi-leg strategy builders
│   ├── session.py              # Breeze session lifecycle
│   ├── chain.py                # Option chain snapshot builder
│   ├── greeks.py               # Black-Scholes Greeks
│   └── risk.py                 # Risk checks and position limits
│
├── collector/
│   ├── store.py                # DataStore (psycopg2 ThreadedConnectionPool)
│   ├── nse_bulk_download.py    # NSE bhavcopy bulk downloader
│   ├── historical.py           # Breeze REST historical downloader
│   └── ...                     # chain, ticks, iv, depth collectors
│
├── static/
│   ├── index.html              # Live Dashboard
│   ├── paper.html              # Paper Trading + Algo Runner
│   ├── charts.html             # OHLCV Charts
│   └── strategies.html         # Signal Generator UI
│
├── .env                        # Your credentials — NOT committed to git
├── .env.example                # Template — copy to .env
└── requirements.txt            # Python dependencies
```

---

## API Reference

### Connection

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/connect` | Connect to Breeze |
| `GET` | `/api/status` | Connection and DB status |

### Paper Trading

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/paper/order` | Place a paper order |
| `POST` | `/api/paper/exit/{pos_id}` | Exit a position |
| `GET` | `/api/paper/summary` | Full portfolio snapshot |
| `POST` | `/api/paper/reset` | Reset all positions and orders |
| `POST` | `/api/paper/capital` | Set starting capital |
| `GET` | `/api/paper/sim-calls` | Simulated Breeze call counts for today |

### Algo Strategies

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/strategy/start` | Arm a strategy (`{strategy_id, auto_exec: true, mode: "paper"}`) |
| `POST` | `/api/strategy/stop` | Disarm a strategy |
| `GET` | `/api/strategy/list` | All strategies with running state and signal counts |
| `GET` | `/api/strategy/signals` | Recent signal history (last 500) |
| `GET` | `/api/intraday/scan` | Trigger a manual intraday scan |

### Data Download

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/data/download` | Breeze backfill for symbol(s) |
| `POST` | `/api/data/nse_bulk` | NSE bhavcopy bulk download |
| `GET` | `/api/data/status` | Download progress and log |
| `POST` | `/api/security-master/download` | Refresh ICICI security master |

### WebSocket — `ws://localhost:8000/ws`

| `type` | When it fires |
|---|---|
| `ltp` | Every price tick from Breeze |
| `quota` | Every 10 s — real Breeze quota + simulated call counts |
| `intraday_signals` | Every scan cycle (15 s during market hours) |
| `strategy_signal` | When an options strategy fires a signal |
| `paper_auto_exit` | When SL / T1 / T2 / EOD auto-exit fires |
| `paper_update` | After any paper order or exit |
| `market_open` | Once daily at 9:15 IST |

---

## Troubleshooting

### "Failed to connect to Breeze" or 401 errors
- The session token expires daily — generate a fresh one each morning
- Verify `BREEZE_API_KEY` and `BREEZE_API_SECRET` are correct in `.env`
- Ensure your ICICI Direct account has API access enabled

### Strategies toggle ON but no trades appear
- Confirm Breeze is connected (green dot on Live Dashboard) — without live prices, signals cannot generate
- Wait for at least one full scan cycle (15 seconds) after market opens at 9:15
- Check the terminal for `Auto intraday trade` or `Auto paper trade` log lines
- Verify the stock isn't already locked (another strategy may already have an open position for it)

### Positions not auto-closing at 15:20
- EOD square-off runs at 15:20 IST — the app uses IST regardless of system timezone
- Confirm the paper monitor loop is running (check terminal: `Paper monitor loop started`)
- If positions are still open after 15:25, use **Exit All** on the positions panel

### Simulated call counter shows 0
- Counters reset at market open (9:15 IST) each day
- They only increment when a strategy is armed (toggle ON) and an auto-trade executes
- No signals = no counters incrementing — check strategy signal feed for signal activity

### "Insufficient paper cash" error
- The auto-trade engine uses 5–10% of available cash per trade
- If capital is fully deployed, no new positions will open
- Click **Change** in the portfolio summary bar to reset capital

### PostgreSQL "connection refused"
- Windows: `services.msc` → verify `postgresql-x64-17` (or your version) is Running
- Try: `psql -h localhost -U postgres -d trading_data -c "SELECT 1"`

### Port 8000 already in use
```powershell
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

---

## Disclaimer

This software is for educational and personal research purposes only. It is not affiliated with ICICI Securities, ICICI Direct, or Breeze Connect.

Options trading involves substantial risk of loss and is not suitable for all investors. Always test thoroughly in paper trading mode before using real capital. The authors accept no responsibility for any financial losses resulting from the use of this software.

**Nothing in this dashboard constitutes financial advice.**

`LIVE_TRADING=false` is the default and must remain so during all paper trading sessions.
