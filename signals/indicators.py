"""
signals/indicators.py — pure, vectorised intraday indicators (numpy).

All functions take 1-D sequences and return a numpy array aligned to the input
length, with np.nan in the warm-up region. Keeping them pure and array-shaped
makes them trivially unit-testable against fixture bars and lets the detectors
read both the latest value and the previous one (for "rising/falling" checks).

Indicators:
  • cumulative_vwap — session VWAP using typical price (H+L+C)/3
  • rsi_wilder      — RSI(n) with Wilder's smoothing
  • atr_wilder      — ATR(n) with Wilder's smoothing
  • rolling_mean    — simple moving average (e.g. 20-bar average volume)
"""

from typing import Sequence

import numpy as np


def typical_price(high: Sequence[float], low: Sequence[float],
                  close: Sequence[float]) -> np.ndarray:
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    return (h + l + c) / 3.0


def cumulative_vwap(high: Sequence[float], low: Sequence[float],
                    close: Sequence[float], volume: Sequence[float]) -> np.ndarray:
    """Cumulative session VWAP from the first bar.

    vwap[i] = Σ(tp·vol)[0..i] / Σ(vol)[0..i], with tp = (H+L+C)/3.

    If cumulative volume is zero up to bar i (e.g. an index feed with no traded
    volume early in the session), VWAP falls back to the cumulative mean typical
    price so the indicator is still defined and monotonic in a sane way.
    """
    tp  = typical_price(high, low, close)
    vol = np.asarray(volume, dtype=float)
    vol = np.where(np.isnan(vol), 0.0, vol)

    cum_pv = np.cumsum(tp * vol)
    cum_v  = np.cumsum(vol)

    out = np.full(tp.shape, np.nan, dtype=float)
    nz  = cum_v > 0
    out[nz] = cum_pv[nz] / cum_v[nz]

    # Fallback where no volume has accumulated yet: cumulative mean typical price.
    if (~nz).any():
        idx = np.arange(1, tp.size + 1, dtype=float)
        cum_tp_mean = np.cumsum(tp) / idx
        out[~nz] = cum_tp_mean[~nz]
    return out


def rsi_wilder(close: Sequence[float], period: int = 14) -> np.ndarray:
    """RSI with Wilder's smoothing. NaN for the first `period` bars."""
    c = np.asarray(close, dtype=float)
    n = c.size
    out = np.full(n, np.nan, dtype=float)
    if n <= period:
        return out

    delta = np.diff(c)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    out[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gain[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i - 1]) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def true_range(high: Sequence[float], low: Sequence[float],
               close: Sequence[float]) -> np.ndarray:
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    prev_c = np.concatenate(([c[0]], c[:-1]))   # TR[0] = high-low
    return np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])


def atr_wilder(high: Sequence[float], low: Sequence[float],
               close: Sequence[float], period: int = 14) -> np.ndarray:
    """ATR with Wilder's smoothing. NaN until `period` true-ranges are available."""
    tr = true_range(high, low, close)
    n = tr.size
    out = np.full(n, np.nan, dtype=float)
    if n <= period:
        return out

    atr = tr[1:period + 1].mean()   # seed from the first `period` true ranges
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr[i]) / period
        out[i] = atr
    return out


def rolling_mean(values: Sequence[float], period: int) -> np.ndarray:
    """Simple moving average. NaN until `period` values are available."""
    v = np.asarray(values, dtype=float)
    n = v.size
    out = np.full(n, np.nan, dtype=float)
    if n < period or period <= 0:
        return out
    csum = np.cumsum(np.insert(v, 0, 0.0))
    out[period - 1:] = (csum[period:] - csum[:-period]) / period
    return out
