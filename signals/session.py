"""
signals/session.py — per-symbol, per-trading-day rolling state.

A SymbolSession accumulates the day's *closed* bars (reset at 09:15 IST) and
exposes the OHLCV series + derived indicator series the detectors need. All
indicator math lives in signals.indicators; this class only assembles arrays
and caches them per bar count.

Two kinds of series live here:

* Intraday series — the raw OHLCV columns, VWAP and the trailing volume gate —
  cover today's bars only. The opening range and VWAP are session concepts and
  must not see yesterday.
* Trailing indicators — RSI, ATR, EMA, Bollinger, Supertrend, Donchian — are
  computed over `history` (prior-session bars) followed by today's bars, then
  sliced so index i still refers to today's bar i. Without that warm-up a
  14-period indicator is NaN until 10:30 on a 5m chart, and every signal fired
  before then reports RSI/ATR as missing.
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
    # Prior-session bars (oldest first) that only feed the trailing indicators.
    history: List[dict] = field(default_factory=list)

    # cached indicator arrays, invalidated whenever a bar is appended
    _cache: Dict[str, np.ndarray] = field(default_factory=dict)

    # ── bar ingestion ─────────────────────────────────────────────────────────

    def reset(self, trade_date: date) -> None:
        """Day boundary: today's bars become history, the intraday state clears."""
        self.trade_date = trade_date
        self.set_history(self.history + self.bars)
        self.bars = []
        self._cache.clear()

    def set_history(self, bars: List[dict]) -> None:
        """Replace the warm-up bars, keeping only the most recent `history_bars`."""
        keep = max(0, int(getattr(self.cfg, "history_bars", 0) or 0))
        self.history = list(bars)[-keep:] if keep else []
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

    # ── trailing indicators (history-warmed) ──────────────────────────────────

    def _full(self, key: str) -> np.ndarray:
        """Column over history + today's bars, for trailing indicators."""
        ck = f"full:{key}"
        if ck not in self._cache:
            self._cache[ck] = np.array(
                [b[key] for b in self.history] + [b[key] for b in self.bars], dtype=float)
        return self._cache[ck]

    def _today(self, arr):
        """Drop the history prefix so the result aligns with `bars`."""
        h = len(self.history)
        if isinstance(arr, tuple):
            return tuple(a[h:] for a in arr)
        return arr[h:]

    def _trailing(self, key: str, fn, *args):
        if key not in self._cache:
            self._cache[key] = self._today(fn(*args))
        return self._cache[key]

    def rsi(self) -> np.ndarray:
        return self.rsi_n(self.cfg.rsi_period)

    def atr(self) -> np.ndarray:
        return self._trailing("atr", indicators.atr_wilder,
                              self._full("high"), self._full("low"), self._full("close"),
                              self.cfg.atr_period)

    def ema(self, period: int) -> np.ndarray:
        return self._trailing(f"ema{period}", indicators.ema, self._full("close"), period)

    def rsi_n(self, period: int) -> np.ndarray:
        return self._trailing(f"rsi{period}", indicators.rsi_wilder,
                              self._full("close"), period)

    def bollinger(self, period: int, k: float):
        return self._trailing(f"bb{period}_{k}", indicators.bollinger_bands,
                              self._full("close"), period, k)

    def supertrend(self, period: int, mult: float):
        return self._trailing(f"st{period}_{mult}", indicators.supertrend,
                              self._full("high"), self._full("low"), self._full("close"),
                              period, mult)

    def donchian(self, period: int):
        return self._trailing(f"dc{period}", indicators.donchian,
                              self._full("high"), self._full("low"), period)

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
