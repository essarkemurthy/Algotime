# Breeze Trading Dashboard

A locally-run web dashboard for NSE/NFO options trading via [ICICI Direct Breeze Connect](https://api.icicidirect.com/). Place manual orders, run algo strategies, monitor live P&L, and practice with a paper trading simulator — all from a browser at `http://localhost:8000`.

---

## Features

| Feature | Description |
|---|---|
| **Live Quotes** | LTP strip for NIFTY, INFY, ONGC, MAXHEALTH — updates every 10 seconds |
| **Manual Orders** | Place any equity/options buy or sell from a form |
| **Trigger Orders** | Set a price level; order fires automatically when spot crosses it |
| **Algo Strategies** | Bull Put Spread and Iron Condor entry scan with Greeks + IV Rank filter |
| **Morning Brief** | AI-generated (Claude Haiku) or rule-based trade ideas at start of day |
| **Research Calls** | Log and act on ICICI research recommendations with structured fields |
| **Order Book** | Fetch today's real orders from Breeze and cancel open ones |
| **Positions** | Live portfolio positions from Breeze |
| **Paper Trading** | Full simulated trading page — no real orders, tracks P&L mark-to-market |

---

## Architecture

```
algo-trade/
├── app.py                  FastAPI server — trading dashboard + WebSocket (run this)
├── main.py                 CLI algo engine (headless, no browser)
├── collect.py              Data collector — streams market data to PostgreSQL
├── options_engine.py       Legacy Breeze engine (referenced by app.py)
├── suggestions.py          Morning Brief — AI (Claude Haiku) or rule-based
├── paper_engine.py         In-memory paper trading simulator
├── static/
│   ├── index.html          Main trading dashboard
│   ├── charts.html         Chart workspace (OHLC + indicators)
│   └── paper.html          Paper trading simulator
├── trade_engine/           Packaged algo engine (strategies, Greeks, risk)
├── collector/              Market data collection package (requires PostgreSQL)
├── scripts/
│   └── setup_db.py         One-time DB schema creation
├── data/                   IV history CSV (auto-created, no DB needed)
├── logs/                   Runtime logs (auto-created)
├── requirements.txt
├── .env.example            Credential template — copy to .env
└── .env                    Your credentials (never committed)
```

> **Two modes:**
> - **Dashboard only** — run `app.py`, no PostgreSQL needed. Orders, charts, paper trading, live quotes all work via direct Breeze API calls.
> - **With data collector** — also run `collect.py` to stream ticks, option chains, and futures into PostgreSQL for historical analysis.

---

## Quick Start

### 1. Clone the repository

```powershell
git clone https://github.com/essarkemurthy/algo-trade.git
cd algo-trade
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

> If PowerShell blocks script execution, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure credentials

Copy the example env file and fill in your details:

```powershell
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

Edit `.env`:

```env
# ── Required: Breeze API (ICICI Direct) ───────────────────────────────────────
BREEZE_API_KEY=your_api_key_here
BREEZE_API_SECRET=your_api_secret_here
BREEZE_SESSION_TOKEN=your_session_token_here

# ── Optional: PostgreSQL (only needed for the data collector) ─────────────────
# The dashboard (app.py) works fine without this.
# Format: postgresql://username:password@host:port/database
DB_URL=postgresql://postgres:your_password@localhost:5432/market_data

# ── Optional: AI Morning Brief (Claude Haiku) ─────────────────────────────────
ANTHROPIC_API_KEY=your_anthropic_key_here
```

> **The `.env` file is listed in `.gitignore` and will never be committed to git.**

### 5. Get your Breeze session token (required daily)

1. Go to [api.icicidirect.com](https://api.icicidirect.com/)
2. Log in with your ICICI Direct credentials
3. After the redirect, copy the `apisession` value from the URL
4. Paste it as `BREEZE_SESSION_TOKEN` in your `.env`

The token expires at the end of each trading day. Repeat every morning before 9:15 AM IST.

### 6. Run the dashboard

**Option A — VS Code (recommended):**
Open the project folder in VS Code and press **F5**. The server starts and the browser opens automatically at `http://localhost:8000`.

**Option B — Terminal:**
```powershell
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate        # macOS/Linux

python app.py
```

Then open `http://localhost:8000` in a browser.

> The dashboard works **without PostgreSQL**. Charts fetch OHLC directly from Breeze. Orders, paper trading, and live quotes all work without a database.

---

## Prerequisites

- Python 3.9 – 3.13
- ICICI Direct Breeze API credentials — sign up at [api.icicidirect.com](https://api.icicidirect.com/)
- PostgreSQL 17+ — **optional**, only needed if you want to run `collect.py` to store historical market data

---

## PostgreSQL Setup (Optional — Data Collector Only)

The trading dashboard (`app.py`) works without PostgreSQL. Only `collect.py` requires it.

### 1. Install PostgreSQL
Download from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/) and install with default settings (port 5432). Note the password you set for the `postgres` user.

### 2. Start the PostgreSQL service
Open **Services** (`Win + R` → `services.msc`), find **postgresql-x64-18**, right-click → **Start**.

Or from an Administrator PowerShell:
```powershell
Start-Service postgresql-x64-18
```

### 3. Create the database
```powershell
$env:PGPASSWORD = "your_postgres_password"
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres -h localhost market_data
```

### 4. Set DB_URL in `.env`
```env
DB_URL=postgresql://postgres:your_password@localhost:5432/market_data
```

### 5. Create all tables
```powershell
.venv\Scripts\Activate.ps1
python scripts/setup_db.py
```

You should see:
```
Tables ready:
  [ok] candles
  [ok] chain_snapshots
  [ok] depth_snapshots
  [ok] futures_candles
  [ok] futures_ticks
  [ok] iv_daily
  [ok] pcr_snapshots
  [ok] spot_ticks
```

### 6. Run the data collector (on trading days)
```powershell
python collect.py
```

The collector runs from 9:15 AM to 3:35 PM IST and self-terminates. It collects spot ticks, futures, full option chains, market depth, PCR, and historical OHLCV for NIFTY, BANKNIFTY, FINNIFTY and 5 large-cap equities.

---

## Daily Workflow

```
08:45  Generate fresh session token on the Breeze portal
       Paste it as BREEZE_SESSION_TOKEN in .env

09:00  Press F5 (VS Code) or: python app.py
       Browser opens at http://localhost:8000

09:15  Click [Connect] on the dashboard
       Enter your API Key and Session Token
       Status dot turns green — LTP strip begins updating

09:15  "Morning Brief" card shows AI/rule-based trade ideas
       Review each suggestion → [Approve] (auto-registers trigger) or [Skip]

09:30  Market opens
       Monitor LTP strip, open positions, P&L summary
       Place manual orders or let trigger orders fire automatically

15:15  Algo engine force-flattens any open strategy positions
       Session ends — revoke token on the Breeze portal
```

---

## Dashboard Sections

### LTP Strip
Live price tiles for NIFTY, INFY, ONGC, MAXHEALTH. Updated every 10 seconds over WebSocket.

### Manual Order
Form fields: Stock, Exchange, Right (CE/PE/Equity), Strike, Expiry, Action (BUY/SELL), Qty, Order Type (Market/Limit), Price. Sends a real order to Breeze on submit.

### Trigger Order
Set a watch price level and direction (above/below). When the LTP crosses the threshold an order fires automatically. Shows as an active watcher until triggered or expired.

### Algo Control
Start/stop Bull Put Spread or Iron Condor entry scans. The algo reads the live option chain, computes IV Rank and delta, and places legs automatically when conditions are met.

### Morning Brief
At page load (or on demand) the engine generates 2–3 trade ideas:
- **With `ANTHROPIC_API_KEY`** — calls Claude Haiku, which analyses NIFTY/Gift Nifty context and suggests structured trades
- **Without API key** — rule-based fallback (NIFTY > 23,500 → bullish idea, below → bearish idea)

Each idea shows Symbol, Action, Strike, Expiry, Qty, Reason. [Approve] registers it as a trigger order. [Skip] dismisses it.

### ICICI Research Calls
Log structured research recommendations with fields: Bias (Bullish/Bearish/Neutral), Type (Options/Equity/Futures), CMP, Entry Trigger, Target, Why, Source. [Act] converts the call into a trigger order. [Dismiss] removes it.

### Order Book & Positions
Two tabs that fetch live data from Breeze:
- **Orders** — today's order list (NSE + NFO), with [Cancel] for pending orders
- **Positions** — current portfolio positions with average price and qty

### Paper Trading
Navigate to `/paper` (or click the "📄 Paper Trading" link in the header). A separate simulated trading page that:
- Shares the same live LTP feed via WebSocket
- Fills orders instantly at LTP (market) or a specified price (limit)
- Tracks cash, invested amount, unrealised and realised P&L
- Supports position averaging and opposing-direction close/reduce
- [Exit] button per position for market exit; [Exit All] to flatten
- Closed positions log with realised P&L per trade
- [Reset] to start fresh; [Change Capital] to adjust starting amount

---

## Paper Trading

The paper trading engine (`paper_engine.py`) is entirely in-memory — no state survives a server restart.

**Starting capital:** ₹10,00,000 (editable in the UI)

**How fills work:**
- Market order → filled at current LTP from the cache; fails if LTP not yet known (requires limit price in that case)
- Limit order → filled immediately at the specified price (no queue simulation)

**Position logic:**
- Same direction as existing position → qty and average price are merged
- Opposite direction → reduces or closes the existing position, books realised P&L

**P&L formula:**
```
Unrealised = (LTP − avg_price) × qty        [for longs]
           = (avg_price − LTP) × qty        [for shorts]
Equity     = Starting Capital + Unrealised + Realised
```

---

## API Reference

All endpoints are on `http://localhost:8000`.

### Connection

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/api/connect` | `{api_key, session_token}` | Connect Breeze session |
| `POST` | `/api/disconnect` | — | Disconnect |
| `GET` | `/api/status` | — | `{connected: bool}` |

### Orders & Positions

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/order/manual` | Place a manual order |
| `POST` | `/api/order/trigger` | Register a trigger order |
| `DELETE` | `/api/order/{order_id}` | Cancel an order |
| `GET` | `/api/breeze/orders` | Fetch today's Breeze order list |
| `GET` | `/api/breeze/positions` | Fetch live Breeze positions |
| `POST` | `/api/breeze/orders/{id}/cancel` | Cancel a specific Breeze order |

### Algo

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/algo/start` | Start strategy (`{strategy: "bull_put_spread"\|"iron_condor"}`) |
| `POST` | `/api/algo/stop` | Stop running algo |

### Paper Trading

| Method | Path | Description |
|---|---|---|
| `GET` | `/paper` | Paper trading page |
| `POST` | `/api/paper/order` | Place a paper order |
| `POST` | `/api/paper/exit/{pos_id}` | Exit a paper position at market |
| `GET` | `/api/paper/summary` | Full portfolio snapshot |
| `POST` | `/api/paper/reset` | Reset all paper positions and orders |
| `POST` | `/api/paper/capital` | Change starting capital (resets portfolio) |

### Suggestions & Research

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/suggestions` | Get morning brief ideas |
| `POST` | `/api/suggestions/{id}/approve` | Approve idea (registers trigger) |
| `POST` | `/api/suggestions/{id}/skip` | Skip idea |
| `GET` | `/api/research` | List research calls |
| `POST` | `/api/research` | Add a research call |
| `DELETE` | `/api/research/{id}` | Delete a research call |
| `POST` | `/api/research/{id}/act` | Convert to trigger order |
| `POST` | `/api/research/{id}/skip` | Mark as skipped |

### WebSocket

`ws://localhost:8000/ws`

Frames broadcast every 10 seconds:

```json
{"type": "ltp",   "data": {"NIFTY": 24312.45, "INFY": 1148.20, ...}}
{"type": "pnl",   "data": {"total_pnl": 2304.0, "unrealised": 1500.0, ...}}
{"type": "alert", "message": "Daily loss limit approaching: ₹35,000 of ₹40,000"}
```

Send `{"type": "ping"}` → server responds `{"type": "pong"}`.

---

## Troubleshooting

### Session expired / 401 errors
Your session token has expired. Generate a new one from the Breeze portal, update `.env`, and press F5 to restart.

### 503 errors from Breeze
Breeze servers are overloaded. The LTP poller automatically backs off (up to 5 minutes). Wait and it will resume.

### Rate limit (Status 5)
Breeze enforces a per-minute call limit. This usually happens if many WebSocket clients connect at once (refresh loop). The poller pauses 300 seconds automatically. Refresh the page once, not repeatedly.

### "No live price for symbol" in paper trading
The LTP cache hasn't received a quote for that symbol yet. Either:
- Connect to Breeze first and wait 10–15 seconds for the first poll
- Or use a **Limit** order and enter the price manually

### WebSocket connects in a loop
Usually caused by opening many browser tabs. Close extra tabs; each tab opens one WebSocket connection.

### Order placed but not appearing in Order Book
The Order Book tab fetches on demand — click the **Orders** tab or refresh it with the reload button. The server also caches one fetch per minute to avoid rate limits.

---

## Algo Strategies

### Bull Put Spread
Sells an OTM put and buys a further-OTM put in the same expiry. Net credit. Profits when NIFTY stays flat or rises.

Entry conditions:
- IV Rank ≥ 40
- Short strike |delta| ≈ 0.25
- Spread width: 100 points (configurable)

### Iron Condor
Bull Put Spread + Bear Call Spread. Four legs, net credit. Profits when NIFTY stays within a range.

Exit triggers (both strategies):
- Debit-to-close ≥ 2× entry credit (stop-loss)
- P&L ≥ 50% of max profit (profit target)
- |Net delta| > 5 (delta breach)
- 15:15 IST (force flatten)

---

## Project Structure

```
algo-trade/
├── main.py                 FastAPI entry point; all REST + WebSocket routes
├── options_engine.py       Original algo engine (BreezeSession, OrderRouter, Greeks, strategies)
├── suggestions.py          Morning Brief generator (SuggestionEngine, MorningBrief, TradeIdea)
├── collect.py              Data collector runner
├── trade_engine/           Refactored engine package
│   ├── config.py           Env var loading + risk/timing constants
│   ├── models.py           Leg, Position data structures
│   ├── session.py          BreezeSession lifecycle
│   ├── chain.py            OptionChainFetcher
│   ├── greeks.py           GreeksEngine + IVRankCalc
│   ├── router.py           OrderRouter
│   ├── risk.py             StopLossManager
│   ├── engine.py           OptionsAlgoEngine orchestrator
│   └── strategies/         BullPutSpread, IronCondor
├── collector/              Market data collection (candles, spot, IV EOD)
├── data/                   iv_history.csv and collected DB data
├── logs/                   Runtime logs
├── requirements.txt        Python dependencies
├── .env                    Credentials — NEVER commit this file
├── .env.example            Template for .env
├── .gitignore
└── .vscode/
    ├── launch.json         F5 → starts server + opens browser
    └── settings.json       Points VS Code to .venv interpreter
```

---

## Disclaimer

This software is for educational and research purposes only. Options trading involves substantial risk of loss and is not suitable for all investors. Paper-trade and back-test thoroughly before risking real capital. The authors are not responsible for any financial losses resulting from use of this software.

Nothing in this dashboard constitutes financial advice.
