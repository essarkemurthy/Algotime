import os
from dataclasses import dataclass, field
from datetime import time as time_t
from typing import Dict, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class CollectorConfig:
    # ── Breeze credentials ────────────────────────────────────────────────────
    api_key: str       = field(default_factory=lambda: os.environ["BREEZE_API_KEY"])
    api_secret: str    = field(default_factory=lambda: os.environ["BREEZE_API_SECRET"])
    session_token: str = field(default_factory=lambda: os.environ["BREEZE_SESSION_TOKEN"])

    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    db_url: str = field(default_factory=lambda: os.environ["DB_URL"])

    # ── Index / equity spot symbols (WebSocket + option chain) ────────────────
    symbols: List[str] = field(default_factory=lambda: ["NIFTY", "BANKNIFTY", "FINNIFTY"])

    # ── Large-cap equity symbols for spot ticks + candles (optional) ──────────
    equity_symbols: List[str] = field(default_factory=lambda: [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    ])

    # ── Futures symbols (near-month + next-month collected per symbol) ────────
    futures_symbols: List[str] = field(default_factory=lambda: ["NIFTY", "BANKNIFTY", "FINNIFTY"])
    futures_num_expiries: int  = 2    # near-month + next-month

    # ── Per-symbol option chain config ────────────────────────────────────────
    symbol_cfg: Dict[str, dict] = field(default_factory=lambda: {
        "NIFTY":     {"strike_step": 50,  "expiry_type": "weekly",  "chain_expiries": 3},
        "BANKNIFTY": {"strike_step": 100, "expiry_type": "weekly",  "chain_expiries": 2},
        "FINNIFTY":  {"strike_step": 50,  "expiry_type": "weekly",  "chain_expiries": 2},
    })

    # ── Option chain collection ────────────────────────────────────────────────
    chain_interval_sec: int  = 300   # REST poll every 5 min
    chain_full: bool         = True  # True = all strikes; False = ATM ± chain_atm_depth
    chain_atm_depth: int     = 15    # used only when chain_full=False

    # ── Spot tick batching ─────────────────────────────────────────────────────
    spot_batch_sec: float = 1.0

    # ── Market depth snapshots ────────────────────────────────────────────────
    collect_depth: bool     = True
    depth_interval_sec: int = 300   # same cadence as chain snapshots

    # ── Historical candle backfill (runs once on startup) ─────────────────────
    collect_historical: bool        = True
    backfill_days: int              = 30
    historical_intervals: List[str] = field(default_factory=lambda: ["1minute", "5minute", "1day"])

    # ── Greeks / IV ───────────────────────────────────────────────────────────
    risk_free_rate: float = 0.065   # 91-day T-bill proxy — update monthly

    # ── Exchange codes ────────────────────────────────────────────────────────
    nse_exchange: str = "NSE"
    nfo_exchange: str = "NFO"

    # ── Market timing (IST) ───────────────────────────────────────────────────
    market_open:  time_t = field(default_factory=lambda: time_t(9,  15))
    market_close: time_t = field(default_factory=lambda: time_t(15, 30))
    shutdown_at:  time_t = field(default_factory=lambda: time_t(15, 35))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def strike_step(self, symbol: str) -> int:
        return self.symbol_cfg.get(symbol, {}).get("strike_step", 50)

    def expiry_type(self, symbol: str) -> str:
        return self.symbol_cfg.get(symbol, {}).get("expiry_type", "weekly")

    def chain_expiries(self, symbol: str) -> int:
        """Number of near expiries to collect option chain for."""
        return self.symbol_cfg.get(symbol, {}).get("chain_expiries", 2)

    @property
    def all_spot_symbols(self) -> List[str]:
        """All symbols that need spot WebSocket subscriptions."""
        return list(dict.fromkeys(self.symbols + self.equity_symbols))
