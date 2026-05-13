import os
from dataclasses import dataclass, field
from datetime import time as time_t
from typing import Literal

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class EngineConfig:
    # Credentials — read from .env, never hardcode
    api_key: str       = field(default_factory=lambda: os.environ["BREEZE_API_KEY"])
    api_secret: str    = field(default_factory=lambda: os.environ["BREEZE_API_SECRET"])
    session_token: str = field(default_factory=lambda: os.environ["BREEZE_SESSION_TOKEN"])

    # Instrument
    underlying:  str = "NIFTY"
    exchange:    str = "NFO"
    lot_size:    int = 50      # verify with current SEBI circular before each series
    num_lots:    int = 1
    strike_step: int = 50

    # Strategy
    strategy:    Literal["bull_put_spread", "iron_condor"] = "bull_put_spread"
    expiry_type: Literal["weekly", "monthly"]              = "weekly"
    short_delta_target: float = 0.25   # target |delta| for the short strike
    spread_width:       int   = 100    # points between short and long strike
    min_credit_pct:     float = 0.25   # skip if credit < this × spread_width

    # Risk
    stop_loss_multiplier: float = 2.0  # exit when debit-to-close ≥ N × entry credit
    profit_target_pct:    float = 0.50 # exit when P&L ≥ N × max_profit
    max_portfolio_delta:  float = 5.0  # emergency exit threshold

    # Greeks / IV
    risk_free_rate:   float = 0.065          # 91-day T-bill proxy (update monthly)
    iv_rank_lookback: int   = 252            # trading days in IV rank window
    min_iv_rank:      float = 40.0           # no entry below this IV rank
    iv_history_file:  str   = "data/iv_history.csv"

    # Timing (IST)
    entry_time:  time_t = field(default_factory=lambda: time_t(9, 30))
    cutoff_time: time_t = field(default_factory=lambda: time_t(15, 0))
    exit_time:   time_t = field(default_factory=lambda: time_t(15, 15))
