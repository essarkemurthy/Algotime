"""
signals/config.py — env-driven configuration for the signal engine.

Mirrors the project's existing config approach (python-dotenv + @dataclass with
field default_factory reading os.environ), e.g. collector.config.CollectorConfig.

Every threshold the spec calls out (STRETCH_ATR, RSI bands, ORB_MINUTES,
VOL_MULT, bar interval) is overridable via an environment variable — nothing is
hardcoded at the detection layer.
"""

import os
from dataclasses import dataclass, field
from datetime import time as time_t
from typing import List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# Supported bar intervals → minutes per bar. Matches the project's interval
# vocabulary ('1m', '5m', '15m', '30m').
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30}


@dataclass
class SignalConfig:
    # ── Bar interval (the cadence signals are evaluated on) ───────────────────
    bar_interval: str = field(default_factory=lambda: os.environ.get("SIGNAL_BAR_INTERVAL", "5m"))

    # ── Indicator periods ─────────────────────────────────────────────────────
    rsi_period: int     = field(default_factory=lambda: _env_int("SIGNAL_RSI_PERIOD", 14))
    atr_period: int     = field(default_factory=lambda: _env_int("SIGNAL_ATR_PERIOD", 14))
    avg_vol_period: int = field(default_factory=lambda: _env_int("SIGNAL_AVG_VOL_PERIOD", 20))

    # ── VWAP Reversal thresholds ──────────────────────────────────────────────
    stretch_atr: float   = field(default_factory=lambda: _env_float("SIGNAL_STRETCH_ATR", 1.0))
    bull_rsi_low: float  = field(default_factory=lambda: _env_float("SIGNAL_BULL_RSI_LOW", 35.0))
    bull_rsi_high: float = field(default_factory=lambda: _env_float("SIGNAL_BULL_RSI_HIGH", 55.0))
    bear_rsi_low: float  = field(default_factory=lambda: _env_float("SIGNAL_BEAR_RSI_LOW", 45.0))
    bear_rsi_high: float = field(default_factory=lambda: _env_float("SIGNAL_BEAR_RSI_HIGH", 65.0))

    # ── ORB thresholds ────────────────────────────────────────────────────────
    orb_minutes: int  = field(default_factory=lambda: _env_int("SIGNAL_ORB_MINUTES", 30))
    vol_mult: float   = field(default_factory=lambda: _env_float("SIGNAL_VOL_MULT", 1.5))

    # ── Notification controls ─────────────────────────────────────────────────
    # enabled  — master kill-switch. False ⇒ detections are still logged to the
    #            signals table + logger, but NO notifications are dispatched.
    # dry_run  — format and print notifications to the console/log instead of
    #            sending them to live channels.
    enabled: bool = field(default_factory=lambda: _env_bool("SIGNAL_NOTIFY_ENABLED", True))
    dry_run: bool = field(default_factory=lambda: _env_bool("SIGNAL_DRY_RUN", False))

    notify_in_app: bool   = field(default_factory=lambda: _env_bool("SIGNAL_NOTIFY_IN_APP", True))
    notify_telegram: bool = field(default_factory=lambda: _env_bool("SIGNAL_NOTIFY_TELEGRAM", False))
    notify_webhook: bool  = field(default_factory=lambda: _env_bool("SIGNAL_NOTIFY_WEBHOOK", False))

    telegram_bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str   = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT_ID", ""))
    webhook_url: str        = field(default_factory=lambda: os.environ.get("SIGNAL_WEBHOOK_URL", ""))

    # ── Symbol filter (None ⇒ evaluate whatever the host feeds in) ────────────
    symbols: Optional[List[str]] = None

    # ── Session timing (IST) — reset all per-symbol state at the open ─────────
    session_start: time_t = field(default_factory=lambda: time_t(9, 15))
    session_end:   time_t = field(default_factory=lambda: time_t(15, 30))

    # ── Derived ───────────────────────────────────────────────────────────────
    @property
    def interval_minutes(self) -> int:
        if self.bar_interval not in INTERVAL_MINUTES:
            raise ValueError(
                f"Unsupported SIGNAL_BAR_INTERVAL={self.bar_interval!r}; "
                f"expected one of {sorted(INTERVAL_MINUTES)}"
            )
        return INTERVAL_MINUTES[self.bar_interval]

    @property
    def orb_bars(self) -> int:
        """Number of bars in the opening range (at least 1)."""
        return max(1, self.orb_minutes // self.interval_minutes)

    @property
    def warmup_bars(self) -> int:
        """Bars needed before any indicator-based signal can be trusted."""
        return max(self.rsi_period, self.atr_period, self.avg_vol_period) + 1
