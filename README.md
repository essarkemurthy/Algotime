# NSE Options Algo Engine

An automated options trading engine for NSE/NFO built on [ICICI Direct Breeze Connect](https://api.icicidirect.com/).
Handles strategy entry, Greeks, IV Rank filtering, and auto stop-loss entirely in Python.

---

## Strategies

| Strategy | Legs | Risk Profile | When to use |
|---|---|---|---|
| **Bull Put Spread** | 2 | Defined | Start here — 4–6 weeks live before moving on |
| **Iron Condor** | 4 | Defined | After Bull Put Spread is stable |
| Short Straddle | 2 | Unlimited | Only after Iron Condor + delta-hedge loop is solid |

---

## Requirements

- Python 3.9 – 3.13
- ICICI Direct Breeze API credentials ([api.icicidirect.com](https://api.icicidirect.com/))
- A fresh **session token** each trading morning (generated via the Breeze portal)

---

## Installation

```powershell
# 1. Clone / download the project
cd d:\trade_on_portal

# 2. Create virtual environment (already done if you received this project)
python -m venv .venv

# 3. Install dependencies
.venv\Scripts\pip install -r requirements.txt
```

---

## Configuration

### Step 1 — Credentials

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in your three Breeze values:

```
BREEZE_API_KEY=your_api_key_here
BREEZE_API_SECRET=your_api_secret_here
BREEZE_SESSION_TOKEN=your_session_token_here
```

> **Session token** expires daily. Generate a new one each morning at
> [api.icicidirect.com](https://api.icicidirect.com/) → Login → copy the token from the URL.

### Step 2 — Trading parameters

All parameters live in `trade_engine/config.py` as a single `EngineConfig` dataclass.
The most important ones:

| Parameter | Default | Description |
|---|---|---|
| `underlying` | `"NIFTY"` | Index or stock symbol |
| `lot_size` | `50` | NIFTY lot size — verify with current SEBI circular |
| `num_lots` | `1` | How many lots to trade |
| `strategy` | `"bull_put_spread"` | `"bull_put_spread"` or `"iron_condor"` |
| `expiry_type` | `"weekly"` | `"weekly"` or `"monthly"` |
| `short_delta_target` | `0.25` | Target absolute delta for the short strike |
| `spread_width` | `100` | Points between short and long strike |
| `min_iv_rank` | `40.0` | Skip entry if IV Rank is below this value |
| `stop_loss_multiplier` | `2.0` | Exit when debit-to-close = N × entry credit |
| `profit_target_pct` | `0.50` | Exit when P&L = N × max possible profit |
| `risk_free_rate` | `0.065` | 91-day T-bill proxy — update monthly |

---

## Running

### One-click (PowerShell)

```powershell
.\run.ps1
```

### With options

```powershell
.\run.ps1 --strategy iron_condor --lots 2 --spread-width 150
```

### All CLI flags

```
python main.py --help

  --strategy       bull_put_spread | iron_condor        (default: bull_put_spread)
  --expiry-type    weekly | monthly                     (default: weekly)
  --underlying     Symbol                               (default: NIFTY)
  --lots           N                                    (default: 1)
  --lot-size       N                                    (default: 50)
  --spread-width   N points                             (default: 100)
  --delta          Target |delta| for short strike      (default: 0.25)
  --min-iv-rank    Minimum IV Rank to enter             (default: 40)
  --sl-mult        Stop-loss multiplier                 (default: 2.0)
  --profit-pct     Profit-target fraction               (default: 0.50)
  --poll           Monitor poll interval seconds        (default: 300)
```

---

## Daily workflow

```
08:45  Generate fresh session token on Breeze portal
       Update BREEZE_SESSION_TOKEN in .env

09:30  .\run.ps1
       Engine connects → fetches chain → computes ATM IV
       Records IV in data/iv_history.csv (IV Rank grows more reliable over time)

       IF IV Rank ≥ 40:
         Selects strikes by delta target
         Places orders (sell short strike, buy long strike)
         Enters monitor loop — polls every 5 minutes

       WHILE market open:
         Fetches live chain → recomputes Greeks → checks stop-loss / profit target
         Exit triggers: 2× debit, 50% profit captured, delta breach, or 15:15 IST

15:15  Force-flatten: all legs closed at market regardless of P&L
       Session ends automatically
```

---

## NSE Option Symbol Format

The engine builds these automatically — shown here for reference:

| Type | Format | Example |
|---|---|---|
| Weekly | `{SYMBOL}{YY}{M}{DD}{STRIKE}{CE/PE}` | `NIFTY2651524500CE` |
| Monthly | `{SYMBOL}{YY}{MON}{STRIKE}{CE/PE}` | `NIFTY26MAY24500CE` |

Weekly month codes: `1–9` for Jan–Sep, `O` = Oct, `N` = Nov, `D` = Dec.

---

## IV Rank

IV Rank tells you whether options are cheap or expensive relative to their own history:

```
IV Rank = (Current ATM IV − 1-year low) / (1-year high − 1-year low) × 100
```

- **Rank < 40** — IV is low, options are cheap, credit spreads give poor premium → engine skips entry
- **Rank 40–60** — moderate — good for credit spreads
- **Rank > 60** — IV is elevated, options are expensive → best conditions for selling premium

The engine records ATM IV daily in `data/iv_history.csv`. The rank becomes reliable after ~20 trading days and accurate after 252 (one full year).

---

## Stop-loss logic

| Trigger | Condition | Action |
|---|---|---|
| Premium stop-loss | Cost to close ≥ 2× entry credit | Market exit all legs |
| Profit target | P&L ≥ 50% of max profit | Market exit all legs |
| Delta breach | \|Net delta\| > 5 | Market exit all legs |
| EOD force-flatten | Time ≥ 15:15 IST | Market exit all legs |

---

## Project structure

```
trade_on_portal/
├── main.py                      CLI entry point
├── run.ps1                      PowerShell launcher
├── requirements.txt
├── .env.example                 Credentials template
├── .env                         Your credentials (never commit this)
├── options_engine.py            Single-file reference implementation
├── data/
│   └── iv_history.csv           Auto-created; grows daily
├── logs/
│   └── options_engine.log       Timestamped trade and error log
└── trade_engine/
    ├── config.py                EngineConfig — all parameters
    ├── models.py                Leg, Position dataclasses
    ├── session.py               Breeze connection management
    ├── symbols.py               NSE symbol builder + expiry calculators
    ├── chain.py                 Option chain fetcher + ATM strike selector
    ├── greeks.py                Greeks engine + IV Rank calculator
    ├── router.py                Order placement (single-leg market orders)
    ├── risk.py                  Stop-loss manager
    ├── engine.py                Main orchestrator
    └── strategies/
        ├── base.py              Abstract Strategy class
        ├── bull_put_spread.py   Bull Put Spread executor
        └── iron_condor.py       Iron Condor executor
```

---

## Adding a new strategy

1. Create `trade_engine/strategies/my_strategy.py` inheriting `Strategy`
2. Implement the `enter(chain, spot, expiry, atm) → Optional[Position]` method
3. Export it from `trade_engine/strategies/__init__.py`
4. Add it to the `run_entry_scan` dispatch in `trade_engine/engine.py`

---

## Logs

All activity is written to both the terminal and `logs/options_engine.log`:

```
2026-05-09 09:31:02 [INFO]  trade_engine.engine   — Underlying=24312.45  Expiry=2026-05-14  Strategy=bull_put_spread
2026-05-09 09:31:04 [INFO]  trade_engine.engine   — ATM IV=13.8%  IV Rank=52.3  IV %ile=61.0
2026-05-09 09:31:05 [INFO]  trade_engine.chain    — Spot 24312.45 → ATM 24300
2026-05-09 09:31:06 [INFO]  trade_engine.router   — ORDER SELL NIFTY2651424100PE 24100 → id=...
2026-05-09 09:31:07 [INFO]  trade_engine.router   — ORDER BUY  NIFTY2651424000PE 24000 → id=...
2026-05-09 09:31:07 [INFO]  trade_engine.strategies.bull_put_spread — BPS entered: sell 24100PE / buy 24000PE | credit=1850.00 max_risk=3150.00
```

---

## Disclaimer

This software is for educational and research purposes.
Options trading involves substantial risk of loss. Paper-trade and back-test thoroughly before going live.
The authors are not responsible for any financial losses resulting from use of this software.
