# Algo Trade Dashboard

A real-time algorithmic trading dashboard for Indian markets, built on ICICI Direct's **Breeze Connect** API. Stream live prices, view interactive charts with technical indicators, build multi-leg option strategies in a paper-trading simulator, run automated signal generators, and store years of market history in PostgreSQL — all from a single browser-based interface.

**No PostgreSQL required to get started.** The app runs entirely in-memory out of the box; PostgreSQL is optional but unlocks historical charting, EOD data persistence, and backtesting.

---

## Table of Contents

1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Running the App](#running-the-app)
6. [Pages & Navigation](#pages--navigation)
7. [Step-by-Step: First Run](#step-by-step-first-run)
8. [Paper Trading](#paper-trading)
9. [Option Strategy Builder](#option-strategy-builder)
10. [Strategy Signal Generators](#strategy-signal-generators)
11. [Charts & Technical Analysis](#charts--technical-analysis)
12. [PostgreSQL Setup (Optional)](#postgresql-setup-optional)
13. [Historical Data Download](#historical-data-download)
14. [NSE Bulk Download (No Breeze Required)](#nse-bulk-download-no-breeze-required)
15. [Database Schema](#database-schema)
16. [Project Structure](#project-structure)
17. [API Reference](#api-reference)
18. [Troubleshooting](#troubleshooting)
19. [Disclaimer](#disclaimer)

---

## Features

| Area | What it does |
|---|---|
| **Live Prices** | WebSocket stream of LTP, volume, bid/ask from Breeze Connect |
| **Option Chain** | Full chain snapshot with Delta, Gamma, Theta, Vega, IV per strike |
| **Interactive Charts** | Candlestick / bar / line with EMA 9/21/50, Bollinger Bands, VWAP, RSI, MACD |
| **Paper Trading** | Zero-risk order simulation with real-time P&L, position management, portfolio summary |
| **Option Strategy Builder** | One-click multi-leg strategies: Iron Condor, Bull Call Spread, Bear Put Spread, Covered Call, Long Straddle |
| **Strategy Alerts** | Auto-fires profit target / stop-loss alerts (50% profit / 2× SL for credit; 80% profit / 50% SL for debit) |
| **Signal Generators** | 5 automated strategies: 0DTE Scalper, IVR Iron Condor, VIX Regime Switcher, Gamma Scalper, Momentum Breakout |
| **Tick → Candle Writer** | Every Breeze WebSocket tick updates live OHLCV candles; closed candles are batch-written to DB every second |
| **Data Collection** | Persists spot ticks, candles, futures, option chain snapshots, PCR, IV rank to PostgreSQL |
| **Breeze Backfill** | Downloads up to 90 days intraday + 2 years daily OHLCV from Breeze for any subscribed symbol |
| **NSE Bulk Download** | Downloads 2 years of Nifty 50 + Sensex 30 equity EOD, futures EOD, and full options EOD — **no Breeze credentials needed** |
| **DB Wizard** | In-app setup wizard — choose No Database or PostgreSQL without editing any config file |
| **Break-even overlays** | Dashed lines on charts mark the break-even prices of active paper strategy positions |
| **Rate Limiter** | Thread-safe sliding-window limiter (75 calls/min, 4,500 calls/day) prevents Breeze API bans |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10 or later** | 3.11 recommended |
| **ICICI Direct account** | With Breeze API access enabled — [api.icicidirect.com](https://api.icicidirect.com/) |
| **PostgreSQL 14+** | **Optional** — only needed for historical charts and data persistence |

> **Breeze API rate limit:** ~4,500 historical data API calls per day. The NSE Bulk Download feature bypasses this limit entirely — it pulls directly from NSE's public bhavcopy archives with no credentials required.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Techultime/algo-trade.git
cd algo-trade

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate the virtual environment
#    Windows PowerShell:
.venv\Scripts\Activate.ps1
#    Windows CMD:
.venv\Scripts\activate.bat
#    macOS / Linux:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

> **Windows PowerShell script execution:** If step 3 fails with "cannot be loaded because running scripts is disabled", run once as Administrator:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

## Configuration

### 1. Create your `.env` file

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 2. Edit `.env` with your credentials

```ini
# ── Breeze API (ICICI Direct) — Required for live data ───────────────────────
BREEZE_API_KEY=your_api_key_here
BREEZE_API_SECRET=your_api_secret_here

# Session token — generate a fresh one each morning (see below)
BREEZE_SESSION_TOKEN=your_session_token_here

# ── PostgreSQL — Optional ─────────────────────────────────────────────────────
# Leave blank to run in in-memory mode (no database required)
DB_URL=postgresql://postgres:your_password@localhost:5432/trading_data
```

> **The `.env` file is in `.gitignore` and will never be committed to git.**

### 3. Getting your Breeze API key and secret

1. Log in at [api.icicidirect.com](https://api.icicidirect.com/)
2. Navigate to **My Apps** → create an app to get your API Key and Secret
3. These are permanent — paste them into `.env` once

### 4. Getting your daily session token (required every morning)

The session token **expires daily** and must be refreshed before trading:

1. Go to [api.icicidirect.com](https://api.icicidirect.com/) and log in
2. Click **Get Session Token** (or the API login link for your app)
3. After redirecting, copy the `apisession` value from the URL
4. Paste it as `BREEZE_SESSION_TOKEN=...` in `.env`
5. Restart the app

**Alternative:** Skip editing `.env` entirely and enter credentials directly in the dashboard's connection wizard when you start the app.

---

## Running the App

```bash
# Make sure the virtual environment is active first
.venv\Scripts\Activate.ps1       # Windows
source .venv/bin/activate         # macOS / Linux

# Start the server
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser at **[http://localhost:8000](http://localhost:8000)**.

For a stable session (no auto-reload on file changes):

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

> **Important:** Always use `--workers 1` (the default). The in-memory paper engine and LTP cache are not shared across processes — multiple workers would give each browser tab an independent state.

---

## Pages & Navigation

| URL | Page | Description |
|---|---|---|
| `/` | **Live Dashboard** | Breeze connection wizard, live option chain, watchlist, LTP ticker |
| `/charts` | **Charts** | Interactive OHLCV charts with technical indicators and a symbol watchlist |
| `/paper` | **Paper Trading** | Simulated order placement, portfolio tracker, option strategy builder, alerts |
| `/strategies` | **Strategy Signals** | Automated signal generators with a real-time signal log |

Navigation links appear in the header on every page.

---

## Step-by-Step: First Run

### Step 1 — Choose your database mode

When you first open [http://localhost:8000](http://localhost:8000) you'll see a two-option setup wizard:

**No Database (recommended for new users)**
Click this to start immediately. Live prices stream directly from Breeze. Charts show live tick data but no historical bars. Everything else — paper trading, option chain, strategy builder — works fully.

**I have PostgreSQL**
Click this to expand a connection form. Enter your PostgreSQL host, port, database name, user, and password. The app tests the connection, auto-creates all tables if they don't exist, and enables historical data features.

### Step 2 — Connect to Breeze

Enter your **API Key**, **API Secret**, and **Session Token**, then click **Connect to Breeze**.

- On success the status dot turns green and live prices begin streaming
- The LTP strip at the top starts updating with real market prices
- The option chain loads automatically for NIFTY

### Step 3 — Explore live data

- Switch the option chain symbol using the dropdown (NIFTY, BANKNIFTY, etc.)
- Click **Charts** in the header to open the chart workspace and add symbols to your watchlist
- Click **Paper Trading** to start simulated trading

---

## Paper Trading

The paper trading simulator (`/paper`) lets you trade with zero risk, tracking positions and P&L in real time.

### Portfolio summary bar

| Tile | What it shows |
|---|---|
| Starting Capital | Configurable — click Change to set a new amount and reset |
| Cash Available | Undeployed capital |
| Invested | Market value of open positions |
| Portfolio Value | Cash + Invested |
| Unrealised P&L | Live mark-to-market P&L on open positions |
| Realised P&L | Cumulative closed-trade P&L |
| Total Return % | Combined return as a percentage of starting capital |

### Placing a single order

1. Enter a stock code (e.g. `NIFTY`, `INFY`, `SBIN`)
2. Choose Exchange (`NSE` for equities, `NFO` for derivatives)
3. Choose Product: **Cash / Equity** or **Options**
4. For options: select Right (CE or PE), Strike, and Expiry date
5. Choose Action (BUY or SELL), Quantity, and Order Type (Market or Limit)
6. Click **Place Paper Order**

Market orders fill at the live LTP. Limit orders fill immediately at the specified price (no queue simulation).

### Position management

- **Open Positions** — live P&L updated via WebSocket. Exit individual positions or use **Exit All** to flatten everything
- **Closed Positions** — full history of closed trades with realised P&L and timestamps
- **Order Log** — chronological log of every paper fill

---

## Option Strategy Builder

Located on the Paper Trading page, the strategy builder lets you enter multi-leg option strategies with a single click — the app calculates strikes, quantities, and leg structure automatically.

### The 5 supported strategies

| Strategy | Legs | Net | Outlook |
|---|---|---|---|
| **Iron Condor** | 4 | Credit | Neutral — range-bound market |
| **Bull Call Spread** | 2 | Debit | Mildly bullish |
| **Bear Put Spread** | 2 | Debit | Mildly bearish |
| **Covered Call** | 2 | Income | Hold futures, generate premium income |
| **Long Straddle** | 2 | Debit | High volatility expected in either direction |

### How to enter a strategy

1. **Select a strategy card** — the relevant parameter fields appear
2. **Enter symbol** — e.g. `NIFTY`, `BANKNIFTY`, `RELIANCE`
3. **Set Expiry Date** — defaults to the nearest Thursday (weekly expiry)
4. **Set Lots** — number of lots (1 lot = symbol's standard lot size)
5. **Width Steps** — spread width in multiples of the strike step (e.g. 2 × 50 = 100 points for NIFTY)
6. **Short / OTM Steps** — how far OTM the short leg is from ATM
7. Click **Preview Legs** — shows all legs with live market prices
8. Optionally enter manual limit prices for any leg
9. Click **Enter Strategy** — all legs fill simultaneously at paper prices

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

### Automatic P&L alerts

| Alert | Trigger | Strategy type |
|---|---|---|
| **TARGET_50** | P&L ≥ 50% of net credit | Credit strategies |
| **SL_2X** | Loss ≥ 2× net credit | Credit strategies |
| **TARGET_80** | P&L ≥ 80% of net debit paid | Debit strategies |
| **SL_50** | Loss ≥ 50% of net debit paid | Debit strategies |

---

## Strategy Signal Generators

The Strategies page (`/strategies`) runs five automated signal generators that analyse live market data and emit actionable signals every 10 seconds.

| # | Strategy | What it monitors | Signal produced |
|---|---|---|---|
| 1 | **0DTE Expiry Scalper** | VWAP and opening-range breakout on expiry days only | `BUY_CALL` / `BUY_PUT` |
| 2 | **IVR Iron Condor** | IV Rank from historical IV database (requires PostgreSQL) | `ENTER_IRON_CONDOR` when IVR > threshold |
| 3 | **VIX Regime Switcher** | India VIX level from Breeze | Regime change: Low / Elevated / High |
| 4 | **Gamma Scalper** | ATM straddle net delta imbalance | `HEDGE_SHORT` / `HEDGE_LONG` |
| 5 | **Momentum Breakout** | Rolling N-period high/low | `BUY_CALL` on N-period high, `BUY_PUT` on low |

### How to run a strategy signal generator

1. Click a strategy card on the Strategies page
2. Select one or more symbols (type to search)
3. Configure parameters (entry timeframe, IVR threshold, delta threshold, lookback period, etc.)
4. Choose **Paper mode** (signals auto-execute as paper trades) or **Live mode** (signals only)
5. Click **Start** — signals appear in the real-time signal log with timestamp, action, confidence, and rationale
6. Click **Stop** to halt the strategy

---

## Charts & Technical Analysis

The Charts page (`/charts`) provides a full workspace for OHLCV analysis.

### Timeframes

| Label | Interval | Data source |
|---|---|---|
| 1m | 1 minute | Live WebSocket ticks (market hours) or DB |
| 5m | 5 minutes | Live WebSocket ticks or DB |
| 30m | 30 minutes | Live WebSocket ticks or DB |
| 1D | Daily | NSE Bulk Download or Breeze backfill → DB |

### Indicators

**Overlay (main chart):** EMA 9, EMA 21, EMA 50, Bollinger Bands (20, 2σ), VWAP

**Sub-charts:** Volume histogram, RSI (14), MACD (12/26/9)

### Signal badge

A live **BUY / SELL / NEUTRAL** badge combines all indicator readings into a single directional bias.

### Break-even overlays

When you switch to a symbol that has an open strategy position in paper trading, dashed amber horizontal lines appear at the break-even prices (e.g. `BE↓ Iron Condor`, `BE↑ Iron Condor`).

### Watchlist

- Click **+ Add** to add any NSE/NFO symbol
- 5 default symbols always present: NIFTY 50, BANK NIFTY, RELIANCE, HDFC BANK, TCS
- Additional symbols persist in browser `localStorage`
- Click any tile to load that symbol's chart

### Data source toggle

Each chart has a **Live / DB** toggle:
- **Live** — builds candles from the current WebSocket tick stream (no history before app start)
- **DB** — loads OHLCV from PostgreSQL (requires historical data downloaded — see below)

### Download button (⬇ Data)

On the chart toolbar, the **⬇ Data** button opens a download panel that fetches Breeze historical data for the currently selected symbol only. Progress, ETA, and a log tail are shown inline. After download completes, the chart automatically reloads from DB.

---

## PostgreSQL Setup (Optional)

PostgreSQL enables historical charting and persistent data collection across sessions.

### 1. Install PostgreSQL

Download from [postgresql.org/download](https://www.postgresql.org/download/) and install with default settings (port 5432).

### 2. Start the PostgreSQL service

**Windows:**
```powershell
Start-Service postgresql-x64-17
```

**macOS (Homebrew):**
```bash
brew services start postgresql@17
```

**Linux:**
```bash
sudo systemctl start postgresql
```

### 3. Create the database

```bash
# Windows
& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres -h localhost trading_data

# macOS / Linux
createdb -U postgres trading_data
```

### 4. Set DB_URL in `.env`

```ini
DB_URL=postgresql://postgres:your_password@localhost:5432/trading_data
```

### 5. Tables are created automatically

All tables are created automatically when the app starts (or when the NSE bulk download runs). No manual schema setup is needed.

### 6. Recommended PostgreSQL performance settings

For high-frequency tick storage run these once in `psql`:

```sql
ALTER SYSTEM SET synchronous_commit      = 'off';
ALTER SYSTEM SET wal_buffers             = '16MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET work_mem                = '16MB';
ALTER SYSTEM SET effective_cache_size    = '512MB';
ALTER SYSTEM SET random_page_cost        = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
SELECT pg_reload_conf();
```

`synchronous_commit = off` gives a large write throughput improvement with minimal data-loss risk (at most ~200ms of ticks on a crash).

---

## Historical Data Download

### Breeze REST API — data availability reference

| Interval | Equity / Cash (NSE) | Futures & Options (NFO) |
|----------|--------------------|-----------------------|
| 1m, 5m, 15m, 30m, 1D | **10 years** | **3 years** |

> **Pagination:** Breeze returns up to **1,000 candles per API call**. The backfill engine chunks requests into 25-day windows for intraday intervals and 365-day windows for daily, paging through the full date range automatically.
>
> **Daily API call budget:** ~4,500 calls/day (or ~1,000 on some plans). A full 1-year backfill of 5 symbols across all intervals costs ~305 calls — safe to run in a single session. Spread multi-year backfills across multiple days.

---

### Option A — Breeze Backfill (intraday + daily, credentials required)

From the Charts page, click the **⬇ Data** button to download historical OHLCV for the currently selected symbol from Breeze.

- **Intraday** (1m, 5m, 30m): up to 90 days
- **Daily** (1D): up to 2 years
- The download fetches only the gap since the last stored candle — safe to re-run

> **Rate limit:** Breeze allows ~4,500 REST API calls per day. For large symbol lists, spread downloads across multiple sessions.

### Option B — Breeze bulk backfill via API

```bash
curl -X POST http://localhost:8000/api/data/download \
  -H "Content-Type: application/json" \
  -d "{\"symbols\": [\"NIFTY\"]}"
```

This triggers a background backfill for the specified symbol(s) using the active Breeze session.

---

## NSE Bulk Download (No Breeze Required)

Downloads **2 years** of Nifty 50 + Sensex 30 historical data from NSE's public bhavcopy archives — **no ICICI/Breeze credentials needed**.

### What it downloads

| Data | Table | Symbols |
|---|---|---|
| Equity EOD (OHLCV, daily) | `candles` (interval=`1d`) | 50 Nifty 50 + 30 Sensex 30 stocks (54 unique) |
| Futures EOD (OHLCV, daily) | `futures_candles` (interval=`1d`) | Same 54 stocks + NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY |
| Options EOD (per strike, daily) | `options_eod` | Same universe — all strikes, all expiries, CE + PE |

### Via API (app must be running)

```bash
# Trigger full 2-year download
curl -X POST http://localhost:8000/api/data/nse_bulk \
  -H "Content-Type: application/json" \
  -d "{\"days\": 730}"

# Equity only (skip F&O)
curl -X POST http://localhost:8000/api/data/nse_bulk \
  -H "Content-Type: application/json" \
  -d "{\"days\": 730, \"equity_only\": true}"

# F&O only (skip equity spot)
curl -X POST http://localhost:8000/api/data/nse_bulk \
  -H "Content-Type: application/json" \
  -d "{\"days\": 730, \"fo_only\": true}"

# Monitor progress
curl http://localhost:8000/api/data/status
```

**Windows CMD** (use escaped double quotes):
```cmd
curl -X POST http://localhost:8000/api/data/nse_bulk -H "Content-Type: application/json" -d "{\"days\": 730}"
```

### Via CLI (no app needed)

```bash
# Full download
python -m collector.nse_bulk_download --days 730

# Equity only
python -m collector.nse_bulk_download --days 730 --equity-only

# F&O only
python -m collector.nse_bulk_download --days 730 --fo-only

# Custom DB URL
python -m collector.nse_bulk_download --days 730 --db-url "postgresql://..."
```

### Key behaviours

- **Resumes automatically** — re-running continues from the last stored date, skipping already-downloaded days
- **Weekends and holidays** skipped automatically (404 dates are silently ignored)
- **Duplicate safe** — equity/futures use `ON CONFLICT DO UPDATE`; options use `ON CONFLICT DO NOTHING`
- **Rate** — ~150 requests/minute (0.4s sleep between dates); a full 730-day run takes ~8–10 minutes

### What intraday data is NOT available from NSE

NSE does not publish free historical intraday data. The 1m, 5m, and 30m candles can only be built from **live WebSocket ticks** during market hours. After the app runs for a few sessions, historical intraday bars will accumulate in the `candles` table.

---

## Database Schema

All tables are created automatically by the app or by `NSEBulkDownloader.run()`.

| Table | Contents | Created by |
|---|---|---|
| `candles` | OHLCV candles at 1m / 5m / 30m / 1d | Live ticks + NSE bulk + Breeze backfill |
| `spot_ticks` | Every WebSocket LTP tick (unlogged for speed) | Live collector |
| `futures_ticks` | Futures contract LTP and open interest | Live collector |
| `futures_candles` | Futures OHLCV at 1d (+ live intervals) | NSE bulk + Breeze backfill |
| `options_eod` | Options OHLCV + OI + Greeks per strike per day | NSE bulk download |
| `chain_snapshots` | Full option chain every 5 minutes (bid/ask, OI, IV, Greeks) | Live collector |
| `depth_snapshots` | 5-level market depth snapshots | Live collector |
| `pcr_snapshots` | Put-Call Ratio per expiry | Live collector |
| `iv_daily` | Daily ATM IV summary for IV Rank / IV Percentile | Live collector |

### `options_eod` schema

```sql
CREATE TABLE options_eod (
    date       date          NOT NULL,
    symbol     text          NOT NULL,
    expiry     date          NOT NULL,
    strike     numeric(12,2) NOT NULL,
    "right"    char(2)       NOT NULL,   -- CE or PE
    open       numeric(12,2),
    high       numeric(12,2),
    low        numeric(12,2),
    close      numeric(12,2),
    settle     numeric(12,2),            -- settlement price (more reliable than close for illiquid strikes)
    volume     bigint        DEFAULT 0,
    oi         bigint        DEFAULT 0,
    oi_change  bigint        DEFAULT 0,
    underlying numeric(12,2),
    PRIMARY KEY (date, symbol, expiry, strike, "right")
);
```

---

## Project Structure

```
algo-trade/
│
├── app.py                          # FastAPI server — all HTTP + WebSocket routes
├── paper_engine.py                 # In-memory paper trading engine
├── options_engine.py               # Breeze session + option chain utilities
├── suggestions.py                  # AI-powered trade suggestions (optional, needs ANTHROPIC_API_KEY)
│
├── trade_engine/
│   ├── config.py                   # Breeze connection config dataclass
│   ├── session.py                  # Breeze session lifecycle
│   ├── chain.py                    # Option chain snapshot builder
│   ├── greeks.py                   # Black-Scholes Greeks via py_vollib
│   ├── strategy_signals.py         # 5 automated signal generators
│   ├── option_strategies.py        # Multi-leg strategy builders (Iron Condor, Spreads, etc.)
│   ├── risk.py                     # Risk checks and position limits
│   └── strategies/                 # Rule-based strategy classes
│       ├── iron_condor.py
│       └── bull_put_spread.py
│
├── collector/
│   ├── runner.py                   # Background data collection orchestrator
│   ├── chain.py                    # Option chain → DB every 5 minutes
│   ├── candles.py                  # Tick → OHLCV candle builder
│   ├── spot.py                     # Spot LTP ticks → DB (batched)
│   ├── futures.py                  # Futures ticks → DB
│   ├── historical.py               # Breeze REST historical downloader → DB (gap-fill)
│   ├── nse_bulk_download.py        # NSE bhavcopy bulk downloader (no credentials needed)
│   ├── depth.py                    # Order book depth → DB
│   ├── iv_eod.py                   # End-of-day IV summary → iv_daily table
│   ├── config.py                   # CollectorConfig dataclass
│   └── store.py                    # DataStore class (psycopg2 ThreadedConnectionPool)
│
├── static/
│   ├── index.html                  # Live Dashboard (wizard, option chain, watchlist)
│   ├── charts.html                 # Interactive OHLCV charts + technical indicators
│   ├── paper.html                  # Paper trading + option strategy builder
│   └── strategies.html             # Automated signal generator UI
│
├── .env.example                    # Copy to .env and fill in credentials
├── .gitignore                      # .env and .venv excluded from git
└── requirements.txt                # Python dependencies
```

---

## API Reference

All endpoints are served by `app.py` on `http://localhost:8000`.

### Connection & DB

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/connect` | Connect to Breeze (`{api_key, api_secret, session_token}`) |
| `GET` | `/api/status` | Connection and DB mode status |
| `POST` | `/api/db/configure` | Configure PostgreSQL (`{host, port, dbname, user, password}`) |
| `POST` | `/api/db/disable` | Switch to in-memory mode |

### Market Data

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/subscribe` | Subscribe symbol to WebSocket feed |
| `GET` | `/api/chain` | Option chain snapshot with Greeks |
| `GET` | `/api/ohlc` | OHLCV from Breeze REST (live) |
| `GET` | `/api/ohlc/db` | OHLCV from PostgreSQL |
| `GET` | `/api/symbols` | Symbol search |

### Historical Data Download

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/data/download` | Breeze backfill for specific symbol(s) — credentials required |
| `POST` | `/api/data/nse_bulk` | NSE bhavcopy bulk download — no credentials needed |
| `GET` | `/api/data/status` | Download progress, ETA, log tail |

**`POST /api/data/download` body:**
```json
{
  "symbols": ["NIFTY"],
  "backfill_days": 90,
  "backfill_days_daily": 730
}
```

**`POST /api/data/nse_bulk` body:**
```json
{
  "days": 730,
  "equity_only": false,
  "fo_only": false
}
```

**`GET /api/data/status` response:**
```json
{
  "status": "running",
  "current": "[2024-05-15] equity=50  futures=180  options=12500",
  "done_items": 45,
  "total_items": 730,
  "eta_sec": 380,
  "running": true,
  "log": ["...last 100 lines..."]
}
```

### Paper Trading — Single Orders

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/paper/order` | Place a paper order |
| `POST` | `/api/paper/exit/{pos_id}` | Exit a single open position |
| `GET` | `/api/paper/summary` | Full portfolio snapshot |
| `POST` | `/api/paper/reset` | Reset all positions and orders |
| `POST` | `/api/paper/capital` | Set starting capital and reset |

### Paper Trading — Option Strategies

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/paper/strategy/plan` | Preview legs + strikes without entering |
| `POST` | `/api/paper/strategy/enter` | Enter a multi-leg strategy trade |
| `POST` | `/api/paper/strategy/exit/{trade_id}` | Exit all legs of a strategy |
| `GET` | `/api/paper/strategies` | All strategy trades with live P&L |

### Automated Signal Runners

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/strategy/start` | Start a signal generator |
| `POST` | `/api/strategy/stop` | Stop a running strategy |
| `GET` | `/api/strategy/list` | Active strategy runs |
| `GET` | `/api/strategy/signals` | Recent signal history |

### WebSocket

Connect at `ws://localhost:8000/ws`

| `type` | Triggered when |
|---|---|
| `init` | On first connect — full state snapshot |
| `ltp` | Every price tick |
| `paper_update` | After any paper order or exit |
| `strategy_signal` | When a signal generator fires |
| `strategy_alert` | When a strategy trade hits target/SL |
| `paper_strategy_entered` | After a multi-leg strategy entry |
| `paper_strategy_closed` | After a strategy exit |

Send `ping` as a plain string to keep the connection alive; the server responds with `pong`.

---

## Troubleshooting

### "Failed to connect to Breeze" or 401 errors

- The session token expires daily — generate a fresh one each morning
- Verify `BREEZE_API_KEY` and `BREEZE_API_SECRET` are correct in `.env`
- Ensure your ICICI Direct account has API access enabled

### Charts show "No data in DB" for 1m / 5m / 30m

Intraday candles are built from live WebSocket ticks — they accumulate during market hours. For daily (1D) charts, run the NSE bulk download first.

### Charts show "No data in DB" for 1D

Run the NSE bulk download:
```cmd
curl -X POST http://localhost:8000/api/data/nse_bulk -H "Content-Type: application/json" -d "{\"days\": 730}"
```
Then switch the chart data source to **DB** and select the **1D** interval.

### NSE bulk download shows "All data already up to date" immediately

The resume logic detected existing data for enough symbols. Force a full re-download by temporarily truncating:
```sql
TRUNCATE candles; TRUNCATE futures_candles; TRUNCATE options_eod;
```
Then re-run the bulk download.

### NSE bulk download: futures/options rows are 0 but equity works

NSE occasionally restructures the F&O bhavcopy ZIP format. Check the log via `GET /api/data/status` for any zip parse errors. The equity and F&O downloads are independent — re-run with `"fo_only": true` to retry only F&O.

### Breeze historical data limit reached

Breeze allows ~4,500 REST API calls per day. If you hit the limit mid-download, remaining symbols fail silently. Use the NSE bulk download instead for equity daily data — it has no rate limit.

### "Test Connection" fails for PostgreSQL

- Verify PostgreSQL is running (Windows: `services.msc`; Linux: `systemctl status postgresql`)
- Check the database exists: `psql -U postgres -c "\l"`
- Try a direct connection: `psql -h localhost -U postgres -d trading_data`

### Port 8000 already in use

```powershell
# Windows
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

```bash
# macOS / Linux
lsof -i :8000 && kill -9 <pid>
```

### Data not persisting across server restarts

Paper trading portfolio, order log, and LTP cache are **in-memory** and reset on every restart. Only PostgreSQL-backed data (candles, ticks, chain snapshots) survives restarts.

### WebSocket keeps reconnecting

The client auto-reconnects every 3 seconds after a disconnect. This is normal if the server is restarting. Avoid opening many browser tabs simultaneously — each tab holds one WebSocket connection.

---

## Disclaimer

This software is for educational and personal research purposes only. It is not affiliated with ICICI Securities, ICICI Direct, or Breeze Connect.

Options trading involves substantial risk of loss and is not suitable for all investors. Always test in paper trading mode and back-test thoroughly before using real capital. The authors accept no responsibility for any financial losses resulting from the use of this software.

Nothing in this dashboard constitutes financial advice.
