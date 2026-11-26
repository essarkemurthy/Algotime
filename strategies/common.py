"""
strategies/common.py — pieces shared by the pure strategy modules.

Re-exports the bar/session plumbing and statistics of `orb_cpr_nifty` (left
untouched because its verdict is on record) and adds what the 2026-11-26
hypotheses need: a generic resampler for any bar size, Wilder RSI/ADX over bar
sequences (continuous across sessions), a generic bracket simulator, an expiry
-day calendar for slices, and a skip-reason funnel for modules whose filters
are not the ORB-CPR ones.
"""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from strategies.orb_cpr_nifty import (  # noqa: F401  (re-exported)
    LONG, SHORT, Bar, atr_wilder, bootstrap_ci, max_drawdown, r_series, summarize)

EXIT_STOP = "stop"
EXIT_BE_STOP = "be_stop"
EXIT_TARGET = "target"
EXIT_TIME = "time"
EXIT_EOD = "eod"


# ── bars ──────────────────────────────────────────────────────────────────────

def resample(df_1m: pd.DataFrame, bar_minutes: int, session_open: time = time(9, 15),
             session_close: time = time(15, 30)) -> pd.DataFrame:
    """1-minute bars -> `bar_minutes` bars anchored at the session open, labelled
    by bar open time (naive IST). Buckets opening at/after the close are dropped."""
    if df_1m.empty:
        return df_1m.iloc[0:0]
    df = df_1m.copy()
    ts = pd.to_datetime(df["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df["ts"] = ts
    df = df.sort_values("ts")
    day = df["ts"].dt.normalize()
    anchor = day + pd.Timedelta(hours=session_open.hour, minutes=session_open.minute)
    offset_min = ((df["ts"] - anchor).dt.total_seconds() // 60)
    bucket = anchor + pd.to_timedelta((offset_min // bar_minutes) * bar_minutes, unit="m")
    df["bucket"] = bucket
    df = df[(offset_min >= 0) & (df["bucket"].dt.time < session_close)]
    out = df.groupby("bucket").agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   volume=("volume", "sum")).reset_index()
    out = out.rename(columns={"bucket": "ts"})
    for c in ("open", "high", "low", "close"):
        out[c] = out[c].astype(float)
    out["volume"] = out["volume"].astype("int64")
    return out


def split_sessions(df_bars: pd.DataFrame, min_bars: int, exclude_weekends: bool = True
                   ) -> Dict[date, List[Bar]]:
    out: Dict[date, List[Bar]] = {}
    if df_bars.empty:
        return out
    ts = pd.to_datetime(df_bars["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df = df_bars.assign(ts=ts).sort_values("ts")
    for d, g in df.groupby(df["ts"].dt.date):
        if len(g) < min_bars:
            continue
        if exclude_weekends and d.weekday() >= 5:
            continue
        out[d] = [Bar(r.ts.to_pydatetime(), float(r.open), float(r.high), float(r.low),
                      float(r.close), int(r.volume)) for r in g.itertuples(index=False)]
    return out


def prepare_sessions(df_1m: pd.DataFrame, bar_minutes: int, min_session_bars: int,
                     session_open: time = time(9, 15), exclude_weekends: bool = True
                     ) -> Dict[date, List[Bar]]:
    return split_sessions(resample(df_1m, bar_minutes, session_open), min_session_bars, exclude_weekends)


def daily_ohlc(sessions: Dict[date, List[Bar]]) -> Tuple[List[date], List[float], List[float],
                                                          List[float], List[float]]:
    days = sorted(sessions)
    opens = [sessions[d][0].open for d in days]
    highs = [max(b.high for b in sessions[d]) for d in days]
    lows = [min(b.low for b in sessions[d]) for d in days]
    closes = [sessions[d][-1].close for d in days]
    return days, opens, highs, lows, closes


# ── Wilder indicators over bar sequences ──────────────────────────────────────

def rsi_wilder(closes: Sequence[float], period: int) -> List[Optional[float]]:
    """Wilder RSI; None for the first `period` elements. Same arithmetic as
    signals.indicators.rsi_wilder (seeded with simple means, then smoothed)."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n)]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period

    def rsi(g: float, l: float) -> float:
        if l == 0.0:
            return 100.0 if g > 0 else 50.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)

    out[period] = rsi(ag, al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i - 1]) / period
        al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = rsi(ag, al)
    return out


def adx_wilder(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               period: int) -> List[Optional[float]]:
    """Wilder ADX. Element i uses bars 0..i. None until 2*period bars exist.

    TR, +DM, -DM are smoothed with Wilder's running sum (seed = sum of the first
    `period` values), DI = 100*DM/TR, DX = 100*|+DI - -DI|/(+DI + -DI), and ADX is
    the Wilder average of DX seeded with the mean of the first `period` DX values.
    """
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < 2 * period + 1:
        return out
    tr = [0.0] * n
    pdm = [0.0] * n
    ndm = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    s_tr = sum(tr[1:period + 1])
    s_p = sum(pdm[1:period + 1])
    s_n = sum(ndm[1:period + 1])
    dx: List[Optional[float]] = [None] * n

    def _dx(stv: float, sp: float, sn: float) -> float:
        if stv <= 0:
            return 0.0
        pdi, ndi = 100.0 * sp / stv, 100.0 * sn / stv
        den = pdi + ndi
        return 100.0 * abs(pdi - ndi) / den if den > 0 else 0.0

    dx[period] = _dx(s_tr, s_p, s_n)
    for i in range(period + 1, n):
        s_tr = s_tr - s_tr / period + tr[i]
        s_p = s_p - s_p / period + pdm[i]
        s_n = s_n - s_n / period + ndm[i]
        dx[i] = _dx(s_tr, s_p, s_n)
    first = 2 * period - 1
    adx = sum(dx[period:first + 1]) / period            # mean of the first `period` DX values
    out[first] = adx
    for i in range(first + 1, n):
        adx = (adx * (period - 1) + dx[i]) / period
        out[i] = adx
    return out


def continuous_indicators(sessions: Dict[date, List[Bar]], adx_period: int, rsi_period: int
                          ) -> Dict[date, Tuple[List[Optional[float]], List[Optional[float]]]]:
    """ADX and RSI over the concatenated bar series of all sessions in date order,
    split back per session so bar k of day d has values that use every bar through
    k (previous sessions included). Returns {day: (adx_list, rsi_list)}."""
    days = sorted(sessions)
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    spans: List[Tuple[date, int, int]] = []
    for d in days:
        bars = sessions[d]
        a = len(closes)
        highs += [b.high for b in bars]
        lows += [b.low for b in bars]
        closes += [b.close for b in bars]
        spans.append((d, a, len(closes)))
    adx = adx_wilder(highs, lows, closes, adx_period)
    rsi = rsi_wilder(closes, rsi_period)
    return {d: (adx[a:b], rsi[a:b]) for d, a, b in spans}


# ── generic bracket simulation ────────────────────────────────────────────────

def simulate_bracket(direction: str, bars_after: Sequence[Bar], stop_dist: float,
                     target_r: float, be_trigger_r: Optional[float], time_exit: time
                     ) -> Optional[Tuple[datetime, float, datetime, float, str]]:
    """Fill at the open of bars_after[0]; stop/target intrabar (stop first);
    optional breakeven after +be_trigger_r*S (effective next bar); time exit at
    the open of the first bar at/after `time_exit`. Returns
    (entry_ts, entry, exit_ts, exit, reason) or None without a next bar."""
    if not bars_after:
        return None
    sgn = 1.0 if direction == LONG else -1.0
    entry_bar = bars_after[0]
    entry = entry_bar.open
    stop = entry - sgn * stop_dist
    target = entry + sgn * stop_dist * target_r
    be_level = entry + sgn * stop_dist * be_trigger_r if be_trigger_r is not None else None
    be_armed = stop_is_be = False
    last = entry_bar
    for bar in bars_after:
        last = bar
        if bar.ts.time() >= time_exit:
            return entry_bar.ts, entry, bar.ts, bar.open, EXIT_TIME
        if be_armed and not stop_is_be:
            stop, stop_is_be = entry, True
        hit_stop = (bar.low <= stop) if sgn > 0 else (bar.high >= stop)
        hit_target = (bar.high >= target) if sgn > 0 else (bar.low <= target)
        if hit_stop:
            return entry_bar.ts, entry, bar.ts, stop, (EXIT_BE_STOP if stop_is_be else EXIT_STOP)
        if hit_target:
            return entry_bar.ts, entry, bar.ts, target, EXIT_TARGET
        if be_level is not None and ((bar.high >= be_level) if sgn > 0 else (bar.low <= be_level)):
            be_armed = True
    return entry_bar.ts, entry, last.ts, last.close, EXIT_EOD


# ── calendar (slices only; holiday shifts ignored) ───────────────────────────

WEEKLY_NIFTY_FROM = date(2019, 2, 11)       # first weekly NIFTY expiry week
TUESDAY_FROM = date(2025, 9, 1)             # NIFTY weekly moved Thursday -> Tuesday


def is_last_weekday_of_month(d: date, weekday: int) -> bool:
    return d.weekday() == weekday and (d + timedelta(days=7)).month != d.month


def is_nifty_expiry_day(d: date) -> bool:
    """Scheduled NIFTY expiry day: monthly last Thursday before Feb-2019, weekly
    Thursday after, weekly Tuesday from the Sep-2025 series."""
    if d >= TUESDAY_FROM:
        return d.weekday() == 1
    if d >= WEEKLY_NIFTY_FROM:
        return d.weekday() == 3
    return is_last_weekday_of_month(d, 3)


# ── funnel from skip reasons ──────────────────────────────────────────────────

def funnel_from_skips(df_1m: pd.DataFrame, sessions: Dict[date, List[Bar]], feats: dict,
                      params, trades: Sequence, skips: Counter, skip_order: Sequence[str]) -> dict:
    """Same dict shape as analysis.funnel, built from the module's own skip
    reasons (sequential): evaluable sessions minus each skip bucket == trades."""
    ts = pd.to_datetime(df_1m["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    dup = int(ts.duplicated().sum())
    per_day = ts.groupby(ts.dt.date).agg(["count", "min"])
    raw_days = list(per_day.index)
    weekend = [d for d in raw_days if d.weekday() >= 5]
    n_bars = per_day["count"] // params.bar_minutes
    short = [d for d in raw_days if d.weekday() < 5 and n_bars[d] < params.min_session_bars]
    valid = sorted(sessions)
    not_915 = [d for d in valid if sessions[d][0].ts.time() != params.session_open]
    with_feats = [d for d in valid if d in feats]
    counts = OrderedDict()
    counts["sessions in 1m data"] = len(raw_days)
    counts["- weekend special sessions"] = len(weekend)
    counts["- fewer than %d bars of %d min" % (params.min_session_bars, params.bar_minutes)] = len(short)
    counts["= valid sessions"] = len(valid)
    counts["- no features (warm-up)"] = len(valid) - len(with_feats)
    counts["= evaluable sessions"] = len(with_feats)
    alive = len(with_feats)
    seen = set()
    for k in list(skip_order) + sorted(set(skips) - set(skip_order)):
        if k in seen:
            continue
        seen.add(k)
        alive -= skips.get(k, 0)
        counts["- skip %s" % k] = skips.get(k, 0)
    by_year = Counter(t.trade_date.year for t in trades)
    days_with_trades = len({t.trade_date for t in trades})
    return {"counts": counts, "duplicates_1m": dup, "weekend": weekend, "short": short,
            "not_0915": not_915, "survivors": alive, "trades": len(trades),
            "trades_by_year": dict(sorted(by_year.items())),
            "survivors_equal_trades": alive == days_with_trades}


def tercile_labels(values: Sequence[float]) -> List[str]:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return []
    q = np.quantile(arr, [1 / 3, 2 / 3])
    return ["T%d" % (1 + int(np.searchsorted(q, v, side="right"))) for v in arr]
