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
    # Breeze credentials — same env vars as the trading engine
    api_key: str       = field(default_factory=lambda: os.environ["BREEZE_API_KEY"])
    api_secret: str    = field(default_factory=lambda: os.environ["BREEZE_API_SECRET"])
    session_token: str = field(default_factory=lambda: os.environ["BREEZE_SESSION_TOKEN"])

    # PostgreSQL — postgresql://user:password@host:port/dbname
    db_url: str = field(default_factory=lambda: os.environ["DB_URL"])

    # Underlyings to collect (both spot ticks and option chains)
    symbols: List[str] = field(default_factory=lambda: ["NIFTY", "BANKNIFTY"])

    # Per-symbol: strike step and expiry type
    # BANKNIFTY lost weekly options in 2023; use monthly for it.
    symbol_cfg: Dict[str, dict] = field(default_factory=lambda: {
        "NIFTY":     {"strike_step": 50,  "expiry_type": "weekly"},
        "BANKNIFTY": {"strike_step": 100, "expiry_type": "monthly"},
    })

    # Collection intervals
    chain_interval_sec: int   = 300    # option chain snapshot every 5 min
    chain_atm_depth:    int   = 10     # ATM ± N strikes each side per snapshot
    spot_batch_sec:     float = 1.0    # flush spot tick buffer every N seconds

    # Greeks / IV
    risk_free_rate: float = 0.065      # 91-day T-bill proxy — update monthly

    # Exchange codes
    nse_exchange: str = "NSE"
    nfo_exchange: str = "NFO"

    # Market timing (IST)
    market_open:  time_t = field(default_factory=lambda: time_t(9,  15))
    market_close: time_t = field(default_factory=lambda: time_t(15, 30))
    shutdown_at:  time_t = field(default_factory=lambda: time_t(15, 35))

    def strike_step(self, symbol: str) -> int:
        return self.symbol_cfg.get(symbol, {}).get("strike_step", 50)

    def expiry_type(self, symbol: str) -> str:
        return self.symbol_cfg.get(symbol, {}).get("expiry_type", "weekly")
