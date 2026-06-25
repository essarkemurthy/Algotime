"""
signals/session.py — per-symbol, per-trading-day rolling state.

A SymbolSession accumulates the day's *closed* bars (reset at 09:15 IST) and
exposes the OHLCV series + derived indicator series the detectors need. All
indicator math lives in signals.indicators; this class only assembles arrays
and caches them per bar count.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import numpy as np

from . import indicators
from .config import SignalConfig


@dataclass
class SymbolSession:
    symbol: str
    cfg: SignalConfig
    trade_date: Optional[date] = None
    bars: List[dict] = field(default_factory=list)

    # cached indicator arrays, invalidated whenever a bar is appended
    _cache: Dict[str, np.ndarray] = field(default_factory=dict)

    # ── bar ingestion ─────────────────────────────────────────────────────────

    def reset(self, trade_date: date) -> None:
        self.trade_date = trade_date
        self.bars.clear()
        self._cache.clear()

    def add_bar(self, bar: dict) -> None:
        """Append a freshly-closed bar dict: ts, open, high, low, close, volume."""
        self.bars.append(bar)
        self._cache.clear()

    @property
    def n(self) -> int:
        return len(self.bars)

    # ── series accessors (cached) ─────────────────────────────────────────────

    def _col(self, key: str) -> np.ndarray:
        if key not in self._cache:
            self._cache[key] = np.array([b[key] for b in self.bars], dtype=float)
        return self._cache[key]

    @property
    def high(self) -> np.ndarray:  return self._col("high")
    @property
    def low(self) -> np.ndarray:   return self._col("low")
    @property
    def close(self) -> np.ndarray: return self._col("close")
    @property
    def volume(self) -> np.ndarray: return self._col("volume")

    def vwap(self) -> np.ndarray:
        if "vwap" not in self._cache:
            self._cache["vwap"] = indicators.cumulative_vwap(
                self.high, self.low, self.close, self.volume)
        return self._cache["vwap"]

    def rsi(self) -> np.ndarray:
        if "rsi" not in self._cache:
            self._cache["rsi"] = indicators.rsi_wilder(self.close, self.cfg.rsi_period)
        return self._cache["rsi"]

    def atr(self) -> np.ndarray:
        if "atr" not in self._cache:
            self._cache["atr"] = indicators.atr_wilder(
                self.high, self.low, self.close, self.cfg.atr_period)
        return self._cache["atr"]

    # ── helpers ───────────────────────────────────────────────────────────────

    def trailing_avg_volume(self, i: int) -> Optional[float]:
        """Mean per-bar volume of up to `avg_vol_period` bars *before* bar i.

        Used both as the ORB volume gate and to report a volume ratio. Returns
        None when there is no prior bar to compare against.
        """
        if i <= 0:
            return None
        lo = max(0, i - self.cfg.avg_vol_period)
        window = self.volume[lo:i]
        if window.size == 0:
            return None
        return float(window.mean())
