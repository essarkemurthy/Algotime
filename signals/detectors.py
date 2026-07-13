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
VWAP_ORB = "VWAP_ORB"
EMA_X = "EMA_X"
SUPERTREND = "SUPERTREND"
VWAP_TREND = "VWAP_TREND"
RSI2 = "RSI2"
BB_REV = "BB_REV"
DONCHIAN = "DONCHIAN"
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

    # The opening range is only valid if the session actually observed the bars
    # from the market open. If the engine came online mid-session (a restart)
    # without a warm-up seed, bars[0] is a later bucket, so high[:orb_bars] is a
    # truncated, wrong range — breaking out against it produces spurious ORBs.
    # Refuse rather than fire on a range that doesn't start at the open.
    if s.trade_date is not None:
        session_open = datetime.combine(s.trade_date, cfg.session_start)
        if s.bars[0]["ts"] > session_open:
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


# ── shared Signal builder ───────────────────────────────────────────────────

def _mk(s: SymbolSession, strategy: str, direction: str, i: int) -> Signal:
    """Assemble a Signal for bar i with the common context fields filled in."""
    vwap = s.vwap()
    rsi  = s.rsi()
    atr  = s.atr()
    return Signal(
        symbol=s.symbol, strategy=strategy, direction=direction,
        ts=s.bars[i]["ts"], trade_date=s.trade_date,
        trigger_price=float(s.close[i]),
        vwap=float(vwap[i]) if _finite(vwap[i]) else float(s.close[i]),
        rsi=float(rsi[i]) if _finite(rsi[i]) else float("nan"),
        vol_ratio=_vol_ratio(s, i),
        atr=float(atr[i]) if _finite(atr[i]) else float("nan"),
    )


# ── trend / momentum ────────────────────────────────────────────────────────

def detect_ema_crossover(s: SymbolSession) -> Optional[Signal]:
    """Fast EMA crossing the slow EMA — the canonical trend-follow entry."""
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None
    fast = s.ema(cfg.ema_fast)
    slow = s.ema(cfg.ema_slow)
    if not all(_finite(x) for x in (fast[i], fast[i - 1], slow[i], slow[i - 1])):
        return None
    direction = None
    if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
        direction = LONG
    elif fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]:
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, EMA_X, direction, i)


def detect_supertrend(s: SymbolSession) -> Optional[Signal]:
    """Supertrend flip — trend direction change confirmed by the ATR band."""
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None
    _line, dirn = s.supertrend(cfg.st_period, cfg.st_mult)
    if dirn[i] == 0 or dirn[i - 1] == 0:      # warm-up
        return None
    direction = None
    if dirn[i] == 1 and dirn[i - 1] == -1:
        direction = LONG
    elif dirn[i] == -1 and dirn[i - 1] == 1:
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, SUPERTREND, direction, i)


def detect_vwap_trend(s: SymbolSession) -> Optional[Signal]:
    """Momentum-confirmed VWAP reclaim: price crosses VWAP with RSI on-side.
    Distinct from VWAP_REV (which fades a stretch); this trades *with* the move."""
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None
    vwap = s.vwap()
    rsi  = s.rsi()
    if not all(_finite(x) for x in (vwap[i], vwap[i - 1], rsi[i])):
        return None
    close = s.close
    direction = None
    if close[i] > vwap[i] and close[i - 1] <= vwap[i - 1] and rsi[i] >= cfg.vwap_trend_rsi:
        direction = LONG
    elif close[i] < vwap[i] and close[i - 1] >= vwap[i - 1] and rsi[i] <= (100.0 - cfg.vwap_trend_rsi):
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, VWAP_TREND, direction, i)


# ── mean-reversion ──────────────────────────────────────────────────────────

def detect_rsi2(s: SymbolSession) -> Optional[Signal]:
    """Connors-style RSI(2): buy a pullback into oversold *within an uptrend*
    (close above the trend EMA), and mirror for shorts."""
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None
    r     = s.rsi_n(cfg.rsi2_period)
    trend = s.ema(cfg.rsi2_trend_ema)
    if not all(_finite(x) for x in (r[i], r[i - 1], trend[i])):
        return None
    close = s.close
    direction = None
    if r[i] < cfg.rsi2_low and r[i - 1] >= cfg.rsi2_low and close[i] > trend[i]:
        direction = LONG
    elif r[i] > cfg.rsi2_high and r[i - 1] <= cfg.rsi2_high and close[i] < trend[i]:
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, RSI2, direction, i)


def detect_bollinger_reversion(s: SymbolSession) -> Optional[Signal]:
    """Reversion back inside the Bollinger band: close re-crosses the lower band
    from below (long) or the upper band from above (short)."""
    cfg = s.cfg
    i = s.n - 1
    if i < 1:
        return None
    _mid, upper, lower = s.bollinger(cfg.bb_period, cfg.bb_k)
    if not all(_finite(x) for x in (upper[i], upper[i - 1], lower[i], lower[i - 1])):
        return None
    close = s.close
    direction = None
    if close[i] > lower[i] and close[i - 1] <= lower[i - 1]:
        direction = LONG
    elif close[i] < upper[i] and close[i - 1] >= upper[i - 1]:
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, BB_REV, direction, i)


# ── breakout ────────────────────────────────────────────────────────────────

def detect_donchian(s: SymbolSession) -> Optional[Signal]:
    """N-bar Donchian breakout, confirmed by elevated volume."""
    cfg = s.cfg
    i = s.n - 1
    if i < cfg.dc_period:
        return None
    up, dn = s.donchian(cfg.dc_period)
    if not (_finite(up[i]) and _finite(dn[i])):
        return None
    avg_vol = s.trailing_avg_volume(i)
    vol_ok = avg_vol is not None and s.volume[i] >= cfg.vol_mult * avg_vol
    if not vol_ok:
        return None
    close = s.close
    direction = None
    if close[i] > up[i]:
        direction = LONG
    elif close[i] < dn[i]:
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, DONCHIAN, direction, i)


def detect_vwap_orb(s: SymbolSession) -> Optional[Signal]:
    """Confluence breakout (backtest-validated, PF 1.08 filtered — 2026-07-13):
    an opening-range breakout that is ALSO VWAP trend-aligned, volume-confirmed and
    RSI on-side. It requires the two best edges (ORB breakout + VWAP_TREND) to agree,
    so it fires less often but with higher conviction than either alone."""
    cfg = s.cfg
    i = s.n - 1
    orb_bars = cfg.orb_bars
    if i < orb_bars:
        return None
    # Opening range must start at the market open (same guard as detect_orb).
    if s.trade_date is not None:
        session_open = datetime.combine(s.trade_date, cfg.session_start)
        if s.bars[0]["ts"] > session_open:
            return None
    vwap = s.vwap()
    rsi = s.rsi()
    if not (_finite(vwap[i]) and _finite(rsi[i])):
        return None
    avg_vol = s.trailing_avg_volume(i)
    if avg_vol is None or s.volume[i] < cfg.vol_mult * avg_vol:
        return None
    or_high = float(s.high[:orb_bars].max())
    or_low  = float(s.low[:orb_bars].min())
    close_i = float(s.close[i])
    direction = None
    if close_i > or_high and close_i > vwap[i] and rsi[i] >= cfg.vwap_trend_rsi:
        direction = LONG
    elif close_i < or_low and close_i < vwap[i] and rsi[i] <= (100.0 - cfg.vwap_trend_rsi):
        direction = SHORT
    if direction is None:
        return None
    return _mk(s, VWAP_ORB, direction, i)


DETECTORS = (
    detect_vwap_reversal,
    detect_orb,
    detect_vwap_orb,
    detect_ema_crossover,
    detect_supertrend,
    detect_vwap_trend,
    detect_rsi2,
    detect_bollinger_reversion,
    detect_donchian,
)
