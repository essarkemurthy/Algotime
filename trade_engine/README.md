# trade_engine — Package Architecture

This document describes each module in the `trade_engine` package, the data flow between them, and how to extend the engine.

---

## Module map

```
trade_engine/
├── config.py          EngineConfig dataclass — single source of truth for all parameters
├── models.py          Leg, Position — shared data structures
├── session.py         BreezeSession — API connection lifecycle
├── symbols.py         SymbolBuilder, nearest_weekly_expiry, nearest_monthly_expiry
├── chain.py           OptionChainFetcher — fetches and normalises the option chain
├── greeks.py          GreeksEngine — IV and Greeks; IVRankCalc — rolling IV history
├── router.py          OrderRouter — places single-leg Breeze market orders
├── risk.py            StopLossManager — monitors open positions and triggers exits
├── engine.py          OptionsAlgoEngine — orchestrates the full trading day
└── strategies/
    ├── base.py             Abstract Strategy base class
    ├── bull_put_spread.py  BullPutSpread
    └── iron_condor.py      IronCondor
```

---

## Data flow

```
main.py
  └─ OptionsAlgoEngine.connect()
       ├─ BreezeSession.connect()          → establishes Breeze WebSocket + REST session
       ├─ OrderRouter(session)
       └─ OptionChainFetcher(session)

  └─ OptionsAlgoEngine.run_entry_scan()
       ├─ BreezeSession.get_spot()         → NSE cash market LTP
       ├─ nearest_weekly/monthly_expiry()  → next Thursday expiry date
       ├─ OptionChainFetcher.fetch()       → raw chain DataFrame (all strikes, both sides)
       ├─ OptionChainFetcher.atm_strike()  → rounds spot to nearest valid strike
       ├─ GreeksEngine.iv()               → single ATM IV (Black-Scholes)
       ├─ IVRankCalc.record()             → appends IV to data/iv_history.csv
       ├─ IVRankCalc.rank()               → IV Rank 0–100
       ├─ GreeksEngine.enrich_chain()     → adds iv/delta/gamma/theta/vega columns
       └─ Strategy.enter()               → selects strikes, checks credit floor, places orders
            ├─ closest_delta_strike()    → finds strike with |delta| nearest target
            ├─ chain_ltp()              → reads LTP for a specific strike/right
            └─ OrderRouter.execute()    → places legs sequentially with 200ms gap

  └─ OptionsAlgoEngine.run_monitor_loop()   (every poll_seconds)
       ├─ BreezeSession.get_spot()
       ├─ OptionChainFetcher.fetch()
       ├─ GreeksEngine.enrich_chain()
       └─ StopLossManager.check()
            ├─ close_cost()            → fetches live LTP for each leg, computes debit to close
            ├─ _net_delta()            → sums signed delta across all legs
            └─ _exit()                 → places reverse legs to close the position
```

---

## Module details

### `config.py` — `EngineConfig`

A `@dataclass` holding every tunable parameter.
Credentials are read from environment variables (via `.env` / `python-dotenv`).

```python
from trade_engine.config import EngineConfig

cfg = EngineConfig(
    underlying="BANKNIFTY",
    lot_size=15,
    num_lots=2,
    strategy="iron_condor",
    spread_width=200,
)
```

---

### `models.py` — `Leg`, `Position`

**`Leg`** — one side of a multi-leg trade:

| Field | Type | Description |
|---|---|---|
| `action` | `"buy"/"sell"` | Direction |
| `right` | `"CE"/"PE"` | Call or Put |
| `strike` | `int` | Strike price |
| `expiry` | `date` | Expiry date |
| `symbol` | `str` | NSE trading symbol |
| `quantity` | `int` | Total units (lots × lot_size) |
| `entry_price` | `float` | LTP at time of order |
| `order_id` | `str` | Breeze order ID (filled after placement) |

**`Position`** — a collection of legs with P&L tracking:

| Field | Type | Description |
|---|---|---|
| `legs` | `List[Leg]` | All legs in this position |
| `net_credit` | `float` | Total premium received (positive = cash in) |
| `max_risk` | `float` | Maximum possible loss |
| `max_profit` | `float` | Maximum possible gain |
| `strategy` | `str` | Strategy name |
| `is_open` | `bool` | Set to `False` on exit |

---

### `symbols.py`

**`SymbolBuilder`** — builds NSE trading symbol strings:

```python
from trade_engine.symbols import SymbolBuilder
from datetime import date

exp = date(2026, 5, 14)
SymbolBuilder.weekly("NIFTY", exp, 24500, "CE")   # → "NIFTY2652424500CE"
SymbolBuilder.monthly("NIFTY", exp, 24500, "CE")  # → "NIFTY26MAY24500CE"
SymbolBuilder.breeze_dt(exp)                       # → "2026-05-14T06:00:00.000Z"
```

**Expiry utilities:**

```python
from trade_engine.symbols import nearest_weekly_expiry, nearest_monthly_expiry

nearest_weekly_expiry()   # next Thursday
nearest_monthly_expiry()  # last Thursday of current (or next) month
```

NSE weekly month encoding:

| Month | Code | Month | Code |
|---|---|---|---|
| Jan | `1` | Jul | `7` |
| Feb | `2` | Aug | `8` |
| Mar | `3` | Sep | `9` |
| Apr | `4` | Oct | `O` |
| May | `5` | Nov | `N` |
| Jun | `6` | Dec | `D` |

---

### `session.py` — `BreezeSession`

Wraps `BreezeConnect`. Generates a session on `connect()` and disconnects the WebSocket on `disconnect()`. Supports use as a context manager.

```python
with BreezeSession(cfg) as session:
    spot = session.get_spot()
```

`get_spot()` queries the NSE cash segment for the underlying's last traded price.

---

### `chain.py` — `OptionChainFetcher`

`fetch(expiry, right="others")` — calls Breeze's `get_option_chain_quotes` and returns a normalised DataFrame with columns:

```
strike_price  right  ltp  open_interest  volume
```

`atm_strike(spot, chain)` — rounds `spot` to `strike_step` then snaps to the nearest available strike in the chain.

---

### `greeks.py`

#### `GreeksEngine`

`iv(price, spot, strike, expiry, right)` — Black-Scholes implied volatility via `py_vollib`. Returns `None` on failure (deep ITM/OTM, below intrinsic).

`greeks(iv, spot, strike, expiry, right)` — returns `{delta, gamma, theta, vega}`:
- `theta` is per-day (divided by 365)
- `vega` is per 1% IV move (divided by 100)

`enrich_chain(chain, spot, expiry)` — adds `iv`, `delta`, `gamma`, `theta`, `vega` columns to the chain DataFrame. Uses `py_vollib_vectorized` for the IV pass (one call for the whole chain), then computes Greeks row-by-row. Gracefully falls back to row-by-row IV if vectorized fails.

#### `IVRankCalc`

Reads/writes `data/iv_history.csv`. One row per trading day: `date, atm_iv`.

```
IV Rank      = (current − 1yr_low)  / (1yr_high − 1yr_low)  × 100
IV Percentile = % of days where ATM IV < current IV
```

Rank becomes meaningful after ~20 days; accurate after 252 days.

---

### `router.py` — `OrderRouter`

`place(leg)` — calls Breeze `place_order` as a market order and returns the `order_id`.

`execute(legs)` — places each leg in sequence with a 200 ms sleep between orders to stay within Breeze rate limits.

Helper functions:

```python
chain_ltp(chain, strike, "put")           # extract LTP from chain df
closest_delta_strike(df, target_delta)    # find strike with nearest |delta|
```

---

### `risk.py` — `StopLossManager`

`close_cost(position)` — fetches live LTP for every leg and computes the net debit to close:
- Short legs: buying back costs `+LTP`
- Long legs: selling receives `−LTP`

`check(position, enriched_chain)` — evaluates all exit rules in priority order:

| Rule | Condition | Typical threshold |
|---|---|---|
| Stop-loss | `close_cost ≥ sl_mult × net_credit` | 2× credit |
| Profit target | `P&L ≥ profit_target_pct × max_profit` | 50% of max |
| Delta breach | `|net_delta| > max_portfolio_delta` | 5 lot-adjusted |
| EOD | Called by engine at `exit_time` | 15:15 IST |

`force_flatten(position)` — unconditional market-order close of all legs.

**Delta sign convention:**
- `py_vollib` returns raw delta: calls positive, puts negative
- Short positions flip the sign: `sign = -1 if leg.action == "sell" else 1`
- Net delta of a flat iron condor ≈ 0; of a bull put spread ≈ small positive

---

### `strategies/base.py` — `Strategy`

Abstract base class. All strategies implement one method:

```python
def enter(
    self,
    chain:  pd.DataFrame,   # enriched chain (has delta column)
    spot:   float,
    expiry: date,
    atm:    int,
) -> Optional[Position]:    # None = skip, Position = entered
```

---

### `strategies/bull_put_spread.py` — `BullPutSpread`

1. Filters puts below ATM with a valid delta
2. Picks `short_strike` = closest |delta| to `short_delta_target` (default 0.25)
3. Sets `long_strike` = `short_strike − spread_width`
4. Checks credit ≥ `spread_width × min_credit_pct` — skips if not
5. Places: SELL short_strike PE → BUY long_strike PE

```
Max profit = credit received
Max loss   = spread_width − credit
Break-even = short_strike − credit_per_share
```

---

### `strategies/iron_condor.py` — `IronCondor`

Same delta selection logic, applied to both sides:

- **Put side:** `short_put`, `long_put = short_put − spread_width`
- **Call side:** `short_call`, `long_call = short_call + spread_width`

Places 4 legs. Total credit = put credit + call credit.

```
Max profit = total credit
Max loss   = spread_width − total credit   (assumes equal-width wings)
```

---

### `engine.py` — `OptionsAlgoEngine`

The top-level class. Composes all modules and drives the two-phase trading day.

**`run_entry_scan()`** — morning phase:
1. Guard: skip if outside `entry_time – cutoff_time` window
2. Get spot → pick expiry → fetch chain → find ATM
3. Compute ATM IV → record in history → compute IV Rank
4. Gate: skip if IV Rank < `min_iv_rank`
5. Enrich chain with Greeks
6. Dispatch to `BullPutSpread` or `IronCondor`

**`run_monitor_loop(poll_seconds)`** — intraday phase:
- Loop: fetch spot → fetch chain → enrich → `StopLossManager.check()`
- Break on: position closed, EOD time reached, `KeyboardInterrupt`

---

## Writing a new strategy

```python
# trade_engine/strategies/bear_call_spread.py
from .base import Strategy
from ..models import Leg, Position
from ..router import chain_ltp, closest_delta_strike
from ..symbols import SymbolBuilder
import logging

log = logging.getLogger(__name__)

class BearCallSpread(Strategy):
    def enter(self, chain, spot, expiry, atm):
        cfg = self.cfg
        calls_above = chain[
            (chain["right"] == "call") &
            (chain["strike_price"] > atm) &
            chain["delta"].notna()
        ].copy()
        if calls_above.empty:
            return None

        short_s = closest_delta_strike(calls_above, cfg.short_delta_target)
        long_s  = short_s + cfg.spread_width
        short_p = chain_ltp(chain, short_s, "call")
        long_p  = chain_ltp(chain, long_s, "call") if long_s in chain["strike_price"].values else 0.0
        credit  = short_p - long_p

        if credit < cfg.spread_width * cfg.min_credit_pct:
            return None

        qty  = cfg.lot_size * cfg.num_lots
        legs = [
            Leg("sell", "CE", short_s, expiry,
                SymbolBuilder.build(cfg.underlying, expiry, short_s, "CE", cfg.expiry_type), qty, short_p),
            Leg("buy",  "CE", long_s,  expiry,
                SymbolBuilder.build(cfg.underlying, expiry, long_s,  "CE", cfg.expiry_type), qty, long_p),
        ]
        self.router.execute(legs)
        return Position(legs, credit * qty, (cfg.spread_width - credit) * qty,
                        credit * qty, "bear_call_spread")
```

Then register it:

```python
# trade_engine/strategies/__init__.py
from .bear_call_spread import BearCallSpread

# trade_engine/engine.py — in run_entry_scan()
strategy_map = {
    "bull_put_spread": BullPutSpread,
    "iron_condor":     IronCondor,
    "bear_call_spread": BearCallSpread,
}
self.position = strategy_map[self.cfg.strategy](...).enter(...)
```

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `breeze-connect` | ≥ 1.0.60 | Breeze REST + WebSocket API |
| `py_vollib` | ≥ 1.0.1 | Black-Scholes IV and Greeks (single option) |
| `py_vollib_vectorized` | ≥ 0.1.1 | Vectorized IV across entire chain at once |
| `python-dotenv` | ≥ 1.0.0 | Loads `.env` credentials into environment |
| `pandas` | ≥ 2.0.0 | Chain DataFrame manipulation |
| `numpy` | ≥ 1.24.0 | Vectorized array operations |
