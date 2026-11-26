"""
strategies/orbx_nifty.py — hypothesis ORBX-15 (hypotheses/ORBX-15.md).

NIFTY 15-minute opening-range breakout on 5-minute bars, confirmed by ADX and
RSI instead of volume (the index has none) or the CPR/gap/OR-size filters of
ORB-CPR-15. Exits are copied from ORB-CPR-15 so only the filter set differs.

Per session t (features from sessions strictly before t):
    ATR(14) Wilder on daily O/H/L/C as of the previous close
    ADX(14), RSI(14) Wilder on the continuous 5-minute series (bar k uses bars..k)
Rules (Params):
    OR = high/low of the first `or_minutes` from 09:15
    LONG : 5m bar close > OR-high, close time in (signal_start, signal_end],
           ADX >= adx_min, RSI >= rsi_line
    SHORT: close < OR-low, ADX >= adx_min, RSI <= rsi_line
    one signal per day; entry = next bar open; S = min(OR range, stop_atr_cap*ATR)
    target = entry +/- target_r*S; stop to entry after +be_trigger_r*S (next bar)
    time exit at `time_exit`; stop before target in one bar
"""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from strategies import common as C
from strategies.common import LONG, SHORT, Bar, atr_wilder, bootstrap_ci, r_series, summarize  # noqa: F401

NAME = "ORBX-15"
CI_LOWER_FLOOR = 0.02            # ledger: variant 2 of the NIFTY ORB family
GRID = {"or_minutes": (15, 30), "adx_min": (20.0, 25.0), "rsi_line": (50.0, 55.0)}

SKIP_NO_FEATURES = "no_features"
SKIP_NO_OR = "no_opening_range"
SKIP_NO_BREAKOUT = "no_breakout"
SKIP_NO_ADX = "adx_undefined"
SKIP_ADX_LOW = "adx_below_min"
SKIP_RSI_SIDE = "rsi_wrong_side"
SKIP_NO_NEXT_BAR = "no_next_bar"
SKIP_ORDER = (SKIP_NO_OR, SKIP_NO_BREAKOUT, SKIP_NO_ADX, SKIP_ADX_LOW, SKIP_RSI_SIDE, SKIP_NO_NEXT_BAR)


@dataclass(frozen=True)
class Params:
    bar_minutes: int = 5
    or_minutes: int = 15
    session_open: time = time(9, 15)
    signal_start: time = time(9, 30)     # earliest eligible bar CLOSE (exclusive)
    signal_end: time = time(11, 0)       # latest eligible bar CLOSE (inclusive)
    time_exit: time = time(15, 15)
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    adx_min: float = 20.0
    rsi_line: float = 50.0
    stop_atr_cap: float = 0.5
    target_r: float = 1.5
    be_trigger_r: float = 1.0
    cost_points: float = 3.0
    min_session_bars: int = 70
    exclude_weekends: bool = True

    @property
    def or_end(self) -> time:
        return (datetime.combine(date(2000, 1, 1), self.session_open)
                + timedelta(minutes=self.or_minutes)).time()


def prepare(df_1m: pd.DataFrame, params: Params = Params()) -> Dict[date, List[Bar]]:
    return C.prepare_sessions(df_1m, params.bar_minutes, params.min_session_bars,
                              params.session_open, params.exclude_weekends)


@dataclass(frozen=True)
class DayFeatures:
    trade_date: date
    prev_date: date
    prev_close: float
    atr: float
    adx: Tuple[Optional[float], ...]     # per bar of the day
    rsi: Tuple[Optional[float], ...]


def daily_features(sessions: Dict[date, List[Bar]], params: Params = Params()) -> Dict[date, DayFeatures]:
    days, opens, highs, lows, closes = C.daily_ohlc(sessions)
    atrs = atr_wilder(highs, lows, closes, params.atr_period)
    intra = C.continuous_indicators(sessions, params.adx_period, params.rsi_period)
    out: Dict[date, DayFeatures] = {}
    for i in range(1, len(days)):
        a = atrs[i - 1]
        if a is None or not math.isfinite(a) or a <= 0:
            continue
        adx, rsi = intra[days[i]]
        out[days[i]] = DayFeatures(trade_date=days[i], prev_date=days[i - 1], prev_close=closes[i - 1],
                                   atr=a, adx=tuple(adx), rsi=tuple(rsi))
    return out


@dataclass(frozen=True)
class Signal:
    trade_date: date
    direction: str
    signal_ts: datetime
    signal_close: float
    or_high: float
    or_low: float
    atr: float
    adx: float
    rsi: float
    day_open: float
    prev_close: float
    stop_dist: float

    @property
    def or_range(self) -> float:
        return self.or_high - self.or_low

    @property
    def gap_pct(self) -> float:
        return (self.day_open - self.prev_close) / self.prev_close * 100.0


class DayState:
    """Feed the day's 5m bars in order with their index; returns the Signal once."""

    def __init__(self, trade_date: date, feats: Optional[DayFeatures], params: Params = Params()):
        self.trade_date, self.feats, self.p = trade_date, feats, params
        self.day_open: Optional[float] = None
        self.or_high, self.or_low, self.or_bars, self.or_done = -math.inf, math.inf, 0, False
        self.skip_reason: Optional[str] = None
        self.signal: Optional[Signal] = None
        self.filters: Counter = Counter()          # why eligible breakout bars were rejected

    @property
    def decided(self) -> bool:
        return self.signal is not None or self.skip_reason is not None

    def on_bar(self, bar: Bar, k: int) -> Optional[Signal]:
        if self.decided:
            return None
        if self.feats is None:
            self.skip_reason = SKIP_NO_FEATURES
            return None
        p, f = self.p, self.feats
        if self.day_open is None:
            self.day_open = bar.open
        t_open, t_close = bar.ts.time(), bar.close_time(p.bar_minutes)
        if t_open < p.or_end:
            self.or_high, self.or_low = max(self.or_high, bar.high), min(self.or_low, bar.low)
            self.or_bars += 1
            if t_close >= p.or_end:
                self.or_done = True
            return None
        if not self.or_done:
            if self.or_bars == 0:
                self.skip_reason = SKIP_NO_OR
                return None
            self.or_done = True
        if t_close > p.signal_end:
            # Window over: report the most specific reason seen on breakout bars.
            if self.filters:
                self.skip_reason = self.filters.most_common(1)[0][0]
            else:
                self.skip_reason = SKIP_NO_BREAKOUT
            return None
        if t_close <= p.signal_start:
            return None
        direction = LONG if bar.close > self.or_high else SHORT if bar.close < self.or_low else None
        if direction is None:
            return None
        adx = f.adx[k] if k < len(f.adx) else None
        rsi = f.rsi[k] if k < len(f.rsi) else None
        if adx is None or rsi is None:
            self.filters[SKIP_NO_ADX] += 1
            return None
        if adx < p.adx_min:
            self.filters[SKIP_ADX_LOW] += 1
            return None
        if (direction == LONG and rsi < p.rsi_line) or (direction == SHORT and rsi > p.rsi_line):
            self.filters[SKIP_RSI_SIDE] += 1
            return None
        s = min(self.or_high - self.or_low, p.stop_atr_cap * f.atr)
        if s <= 0:
            self.skip_reason = SKIP_NO_OR
            return None
        self.signal = Signal(trade_date=self.trade_date, direction=direction,
                             signal_ts=bar.ts + timedelta(minutes=p.bar_minutes), signal_close=bar.close,
                             or_high=self.or_high, or_low=self.or_low, atr=f.atr, adx=adx, rsi=rsi,
                             day_open=self.day_open, prev_close=f.prev_close, stop_dist=s)
        return self.signal


@dataclass(frozen=True)
class Trade:
    trade_date: date
    direction: str
    signal_ts: datetime
    entry_ts: datetime
    entry: float
    stop_dist: float
    exit_ts: datetime
    exit: float
    reason: str
    atr: float
    or_range: float
    adx: float
    rsi: float
    gap_pct: float

    @property
    def points(self) -> float:
        return (self.exit - self.entry) * (1.0 if self.direction == LONG else -1.0)

    @property
    def r_gross(self) -> float:
        return self.points / self.stop_dist

    def r_net(self, cost_points: float) -> float:
        return self.r_gross - cost_points / self.stop_dist


def simulate_trade(sig: Signal, bars_after: Sequence[Bar], params: Params = Params()) -> Optional[Trade]:
    res = C.simulate_bracket(sig.direction, bars_after, sig.stop_dist, params.target_r,
                             params.be_trigger_r, params.time_exit)
    if res is None:
        return None
    entry_ts, entry, exit_ts, exit_px, reason = res
    return Trade(trade_date=sig.trade_date, direction=sig.direction, signal_ts=sig.signal_ts,
                 entry_ts=entry_ts, entry=entry, stop_dist=sig.stop_dist, exit_ts=exit_ts,
                 exit=exit_px, reason=reason, atr=sig.atr, or_range=sig.or_range, adx=sig.adx,
                 rsi=sig.rsi, gap_pct=sig.gap_pct)


def simulate_day(trade_date: date, bars: Sequence[Bar], feats: Optional[DayFeatures],
                 params: Params = Params()) -> Tuple[Optional[Trade], Optional[str]]:
    state = DayState(trade_date, feats, params)
    for k, bar in enumerate(bars):
        sig = state.on_bar(bar, k)
        if sig is not None:
            trade = simulate_trade(sig, bars[k + 1:], params)
            return trade, (None if trade else SKIP_NO_NEXT_BAR)
        if state.skip_reason is not None:
            return None, state.skip_reason
    if state.filters:
        return None, state.filters.most_common(1)[0][0]
    return None, state.skip_reason or SKIP_NO_BREAKOUT


def run(sessions: Dict[date, List[Bar]], feats: Dict[date, DayFeatures], params: Params = Params(),
        days: Optional[Iterable[date]] = None) -> Tuple[List[Trade], Counter]:
    trades: List[Trade] = []
    skips: Counter = Counter()
    for d in sorted(days if days is not None else sessions):
        bars = sessions.get(d)
        if not bars:
            continue
        t, why = simulate_day(d, bars, feats.get(d), params)
        if t is not None:
            trades.append(t)
        else:
            skips[why or SKIP_NO_BREAKOUT] += 1
    return trades, skips


# ── report hooks used by strategies/backtest.py and strategies/analysis.py ────

def funnel(df_1m, sessions, feats, params: Params, trades: Sequence[Trade]) -> dict:
    _, skips = run(sessions, feats, params)
    return C.funnel_from_skips(df_1m, sessions, feats, params, trades, skips, SKIP_ORDER)


def slice_dims(trades: Sequence[Trade]) -> "OrderedDict[str, List[str]]":
    """Pre-registered slices (hypotheses/ORBX-15.md): one label per trade per dimension."""
    out: "OrderedDict[str, List[str]]" = OrderedDict()
    out["year"] = [str(t.trade_date.year) for t in trades]
    out["side"] = [t.direction for t in trades]
    out["adx_at_entry"] = ["20-25" if t.adx < 25 else "25-30" if t.adx < 30 else "30+" for t in trades]
    out["rsi_at_entry"] = [("50-60" if t.rsi < 60 else ">60") if t.direction == LONG
                           else ("40-50" if t.rsi > 40 else "<40") for t in trades]
    out["or_atr_tercile"] = C.tercile_labels([t.or_range / t.atr for t in trades])
    out["gap_vs_side"] = ["with" if (t.gap_pct > 0) == (t.direction == LONG) else "against" for t in trades]
    out["weekday"] = [t.trade_date.strftime("%a") for t in trades]
    out["expiry_day"] = ["expiry" if C.is_nifty_expiry_day(t.trade_date) else "other" for t in trades]
    out["signal_hour"] = ["first_hour" if t.signal_ts.time() <= time(10, 15) else "later" for t in trades]
    return out


def trade_row(t: Trade) -> dict:
    return {"trade_date": t.trade_date, "direction": t.direction, "signal_ts": t.signal_ts,
            "entry_ts": t.entry_ts, "entry": t.entry, "stop_dist": t.stop_dist, "exit_ts": t.exit_ts,
            "exit": t.exit, "reason": t.reason, "points": t.points, "r_gross": t.r_gross,
            "r_net_3": t.r_net(3.0), "atr": t.atr, "or_range": t.or_range, "adx": t.adx, "rsi": t.rsi,
            "gap_pct": t.gap_pct}
