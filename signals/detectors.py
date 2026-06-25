"""
signals/detectors.py — VWAP Reversal + ORB signal logic (pure functions).

Each detector inspects the *latest* closed bar of a SymbolSession and returns a
Signal or None. They are pure (no I/O, no notifications) and deterministic, so
they can be unit-tested directly against fixture bars.

Conventions
-----------
"earlier in the session" means a strictly-prior bar (index < current).
"stretched below VWAP" is measured on the bar close: vwap - close.
"rising / falling" RSI compares the latest RSI to the previous bar's RSI.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import numpy as np

from .session import SymbolSession

VWAP_REV = "VWAP_REV"
ORB = "ORB"
LONG = "LONG"
SHORT = "SHORT"


@dataclass
class Signal:
    symbol: str
    strategy: str        # 'VWAP_REV' | 'ORB'
    direction: str       # 'LONG' | 'SHORT'
    ts: datetime         # timestamp of the bar that triggered (bar open, IST)
    trade_date: date
    trigger_price: float
    vwap: float
    rsi: float
    vol_ratio: float
    atr: float

    @property
    def dedup_key(self) -> tuple:
        return (self.trade_date, self.symbol, self.strategy, self.direction)


def _finite(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _vol_ratio(s: SymbolSession, i: int) -> float:
    avg = s.trailing_avg_volume(i)
    if not avg:        # None or 0 → undefined ratio
        return 0.0
    return float(s.volume[i] / avg)


def detect_vwap_reversal(s: SymbolSession) -> Optional[Signal]:
    """Mean-reversion back through VWAP after an ATR-sized stretch.

    Bullish: some earlier bar closed >= STRETCH_ATR·ATR *below* VWAP, the latest
    bar crosses from <=VWAP to >VWAP, and RSI is within the bullish band and
    rising. Bearish mirrors it.
    """
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None

    vwap = s.vwap()
    rsi  = s.rsi()
    atr  = s.atr()
    close = s.close

    if not (_finite(rsi[i]) and _finite(rsi[i - 1]) and _finite(atr[i])
            and _finite(vwap[i]) and _finite(vwap[i - 1])):
        return None

    # ATR-sized stretch on any strictly-earlier bar where ATR was defined.
    stretch = cfg.stretch_atr * atr
    below_earlier = above_earlier = False
    for j in range(i):
        if not _finite(atr[j]) or not _finite(vwap[j]):
            continue
        if (vwap[j] - close[j]) >= stretch[j]:
            below_earlier = True
        if (close[j] - vwap[j]) >= stretch[j]:
            above_earlier = True

    cross_up   = close[i] > vwap[i] and close[i - 1] <= vwap[i - 1]
    cross_down = close[i] < vwap[i] and close[i - 1] >= vwap[i - 1]
    rsi_rising  = rsi[i] > rsi[i - 1]
    rsi_falling = rsi[i] < rsi[i - 1]

    direction = None
    if (below_earlier and cross_up and rsi_rising
            and cfg.bull_rsi_low <= rsi[i] <= cfg.bull_rsi_high):
        direction = LONG
    elif (above_earlier and cross_down and rsi_falling
            and cfg.bear_rsi_low <= rsi[i] <= cfg.bear_rsi_high):
        direction = SHORT

    if direction is None:
        return None

    return Signal(
        symbol=s.symbol, strategy=VWAP_REV, direction=direction,
        ts=s.bars[i]["ts"], trade_date=s.trade_date,
        trigger_price=float(close[i]), vwap=float(vwap[i]),
        rsi=float(rsi[i]), vol_ratio=_vol_ratio(s, i), atr=float(atr[i]),
    )


def detect_orb(s: SymbolSession) -> Optional[Signal]:
    """First close beyond the opening range, confirmed by elevated volume.

    Opening range = high/low of the first `orb_bars` bars from 09:15. A long is
    the first bar (after the range) closing above OR-high; a short mirrors it.
    Requires breakout-bar volume >= VOL_MULT · trailing average volume.

    Dedup (first valid breakout per side per day) is enforced by the engine via
    the signal's dedup_key, so this returns the breakout whenever it is seen.
    """
    cfg = s.cfg
    i = s.n - 1
    orb_bars = cfg.orb_bars
    if i < orb_bars:        # still inside (or just completing) the opening range
        return None

    or_high = float(s.high[:orb_bars].max())
    or_low  = float(s.low[:orb_bars].min())
    close_i = float(s.close[i])

    avg_vol = s.trailing_avg_volume(i)
    if avg_vol is None:
        return None
    vol_ok = s.volume[i] >= cfg.vol_mult * avg_vol
    vol_ratio = _vol_ratio(s, i)
    if not vol_ok:
        return None

    direction = None
    if close_i > or_high:
        direction = LONG
    elif close_i < or_low:
        direction = SHORT
    if direction is None:
        return None

    atr = s.atr()
    vwap = s.vwap()
    return Signal(
        symbol=s.symbol, strategy=ORB, direction=direction,
        ts=s.bars[i]["ts"], trade_date=s.trade_date,
        trigger_price=close_i,
        vwap=float(vwap[i]) if _finite(vwap[i]) else close_i,
        rsi=float(s.rsi()[i]) if _finite(s.rsi()[i]) else float("nan"),
        vol_ratio=vol_ratio,
        atr=float(atr[i]) if _finite(atr[i]) else float("nan"),
    )


DETECTORS = (detect_vwap_reversal, detect_orb)
