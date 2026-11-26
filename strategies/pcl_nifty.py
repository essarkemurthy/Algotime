"""
strategies/pcl_nifty.py — hypothesis PCL-15 (hypotheses/PCL-15.md).

NIFTY intraday pivot / CPR / Camarilla level system on 15-minute bars.

Per session t (from session t-1's O/H/L/C only):
    P=(H+L+C)/3  R1=2P-L  S1=2P-H  BC=(H+L)/2  TC=2P-BC   (CPR top/bottom = max/min)
    H3=C+1.1(H-L)/4  H4=C+1.1(H-L)/2  L3=C-1.1(H-L)/4  L4=C-1.1(H-L)/2
    ATR(14) Wilder on daily bars as of the previous close
    round levels: multiples of `round_step` inside [L4-ATR, H4+ATR]
    ladder = sorted union, levels closer than merge_atr*ATR merged (keep lower)
ADX(14), RSI(14) on the continuous 15-minute series.
Day type at the close of the first bar: TREND if |open-prev_close| > gap_atr*ATR or
first-bar range > or_atr*ATR, else RANGE. Bias per bar: +1 close > CPR top & ADX>=adx_min
& RSI>rsi_mid; -1 mirror below CPR bottom; else 0.
Entries on bar closes in (signal_start, signal_end], one position at a time, at most
max_entries per day:
    TREND LONG : close > L >= prev close for L in {R1} u round, bias == +1   (SHORT mirror on {S1} u round)
    RANGE LONG : low <= E < close and prev close > E for E in {S1, L3, CPR bottom}, bias != -1
                 (SHORT mirror on {R1, H3, CPR top}, bias != +1)
Fill next bar open. Stop = nearest ladder level below entry - buffer_atr*ATR (risk in
[risk_min_atr, risk_max_atr]*ATR else skip). T1/T2 = next two ladder levels above entry;
skip unless T2-entry >= rr_min*risk. Two half-units: half 1 exits at T1, half 2 at T2.
When a bar touches a ladder level above entry, the stop moves to that level - buffer
from the next bar. Stops/targets intrabar, stop first. Time exit at `time_exit` open.
R = mean(points of the halves) / risk, net of cost_points.
"""

from __future__ import annotations

import math
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from strategies import common as C
from strategies.common import LONG, SHORT, Bar, atr_wilder, bootstrap_ci, r_series, summarize  # noqa: F401

NAME = "PCL-15"
CI_LOWER_FLOOR = 0.0
GRID = {"gap_atr": (0.75, 1.0), "or_atr": (0.15, 0.20, 0.25), "adx_min": (20.0, 25.0),
        "buffer_atr": (0.10, 0.15, 0.20)}

TREND, RANGE = "TREND", "RANGE"
SKIP_NO_FEATURES = "no_features"
SKIP_NO_SIGNAL = "no_signal"
SKIP_ORDER = (SKIP_NO_SIGNAL, "rr_too_low", "risk_out_of_band", "no_level_below", "no_t2", "no_next_bar")


@dataclass(frozen=True)
class Params:
    bar_minutes: int = 15
    session_open: time = time(9, 15)
    signal_start: time = time(9, 30)      # earliest eligible bar CLOSE (exclusive)
    signal_end: time = time(14, 30)       # latest eligible bar CLOSE (inclusive)
    time_exit: time = time(15, 0)
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    gap_atr: float = 1.0
    or_atr: float = 0.20
    adx_min: float = 20.0
    rsi_mid: float = 50.0
    buffer_atr: float = 0.15
    round_step: int = 100
    merge_atr: float = 0.05
    risk_min_atr: float = 0.10
    risk_max_atr: float = 1.0
    rr_min: float = 2.0
    max_entries: int = 2
    cost_points: float = 3.0
    min_session_bars: int = 23            # 15-minute bars; a full session has 25
    exclude_weekends: bool = True


def prepare(df_1m: pd.DataFrame, params: Params = Params()) -> Dict[date, List[Bar]]:
    return C.prepare_sessions(df_1m, params.bar_minutes, params.min_session_bars,
                              params.session_open, params.exclude_weekends)


# ── levels ────────────────────────────────────────────────────────────────────

PIVOT, CAMARILLA, ROUND = "pivot", "camarilla", "round"


def pivot_levels(h: float, l: float, c: float) -> Dict[str, float]:
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = 2.0 * p - bc
    rng = h - l
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "BC": bc, "TC": tc,
            "CPR_TOP": max(bc, tc), "CPR_BOTTOM": min(bc, tc),
            "H3": c + 1.1 * rng / 4, "H4": c + 1.1 * rng / 2,
            "L3": c - 1.1 * rng / 4, "L4": c - 1.1 * rng / 2}


def build_ladder(lv: Dict[str, float], atr: float, round_step: int, merge_atr: float
                 ) -> List[Tuple[float, str]]:
    """Sorted (level, type) with near-duplicates merged (keep the lower)."""
    raw: List[Tuple[float, str]] = [(lv[k], PIVOT) for k in ("P", "R1", "S1", "CPR_TOP", "CPR_BOTTOM")]
    raw += [(lv[k], CAMARILLA) for k in ("H3", "H4", "L3", "L4")]
    lo, hi = lv["L4"] - atr, lv["H4"] + atr
    r = math.ceil(lo / round_step) * round_step
    while r <= hi:
        raw.append((float(r), ROUND))
        r += round_step
    raw.sort(key=lambda x: x[0])
    out: List[Tuple[float, str]] = []
    for level, typ in raw:
        if out and level - out[-1][0] < merge_atr * atr:
            continue
        out.append((level, typ))
    return out


@dataclass(frozen=True)
class DayFeatures:
    trade_date: date
    prev_date: date
    prev_close: float
    atr: float
    levels: Dict[str, float]
    ladder: Tuple[Tuple[float, str], ...]
    adx: Tuple[Optional[float], ...]
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
        lv = pivot_levels(highs[i - 1], lows[i - 1], closes[i - 1])
        ladder = build_ladder(lv, a, params.round_step, params.merge_atr)
        adx, rsi = intra[days[i]]
        out[days[i]] = DayFeatures(trade_date=days[i], prev_date=days[i - 1], prev_close=closes[i - 1],
                                   atr=a, levels=lv, ladder=tuple(ladder), adx=tuple(adx), rsi=tuple(rsi))
    return out


# ── signals ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Signal:
    trade_date: date
    direction: str
    day_type: str
    level: float
    level_type: str
    bias: int
    signal_ts: datetime
    signal_close: float
    atr: float
    adx: Optional[float]
    rsi: Optional[float]
    day_open: float
    prev_close: float
    or_range: float

    @property
    def gap_pct(self) -> float:
        return (self.day_open - self.prev_close) / self.prev_close * 100.0


def bias_of(close: float, adx: Optional[float], rsi: Optional[float], f: DayFeatures, p: Params) -> int:
    if adx is None or rsi is None or adx < p.adx_min:
        return 0
    if close > f.levels["CPR_TOP"] and rsi > p.rsi_mid:
        return 1
    if close < f.levels["CPR_BOTTOM"] and rsi < p.rsi_mid:
        return -1
    return 0


def day_type_of(day_open: float, first_bar: Bar, f: DayFeatures, p: Params) -> str:
    gap = abs(day_open - f.prev_close)
    if gap > p.gap_atr * f.atr or (first_bar.high - first_bar.low) > p.or_atr * f.atr:
        return TREND
    return RANGE


def level_type_of(level: float, f: DayFeatures) -> str:
    for lv, typ in f.ladder:
        if abs(lv - level) < 1e-9:
            return typ
    return ROUND


def find_signal(bar: Bar, prev: Bar, k: int, day_type: str, f: DayFeatures, p: Params,
                day_open: float, or_range: float) -> Optional[Signal]:
    adx = f.adx[k] if k < len(f.adx) else None
    rsi = f.rsi[k] if k < len(f.rsi) else None
    b = bias_of(bar.close, adx, rsi, f, p)
    lv = f.levels
    rounds = [l for l, t in f.ladder if t == ROUND]
    direction = level = ltype = None
    if day_type == TREND:
        if b == 1:
            cands = [(L, PIVOT) for L in [lv["R1"]] if bar.close > L >= prev.close]
            cands += [(L, ROUND) for L in rounds if bar.close > L >= prev.close]
            if cands:
                direction, (level, ltype) = LONG, max(cands, key=lambda x: x[0])
        elif b == -1:
            cands = [(L, PIVOT) for L in [lv["S1"]] if bar.close < L <= prev.close]
            cands += [(L, ROUND) for L in rounds if bar.close < L <= prev.close]
            if cands:
                direction, (level, ltype) = SHORT, min(cands, key=lambda x: x[0])
    else:
        if b != -1:
            cands = [(E, t) for E, t in ((lv["S1"], PIVOT), (lv["L3"], CAMARILLA), (lv["CPR_BOTTOM"], PIVOT))
                     if bar.low <= E < bar.close and prev.close > E]
            if cands:
                direction, (level, ltype) = LONG, min(cands, key=lambda x: x[0])
        if direction is None and b != 1:
            cands = [(E, t) for E, t in ((lv["R1"], PIVOT), (lv["H3"], CAMARILLA), (lv["CPR_TOP"], PIVOT))
                     if bar.high >= E > bar.close and prev.close < E]
            if cands:
                direction, (level, ltype) = SHORT, max(cands, key=lambda x: x[0])
    if direction is None:
        return None
    return Signal(trade_date=f.trade_date, direction=direction, day_type=day_type, level=level,
                  level_type=ltype, bias=b, signal_ts=bar.ts + timedelta(minutes=p.bar_minutes),
                  signal_close=bar.close, atr=f.atr, adx=adx, rsi=rsi, day_open=day_open,
                  prev_close=f.prev_close, or_range=or_range)


# ── trade ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Trade:
    trade_date: date
    direction: str
    day_type: str
    level_type: str
    bias: int
    signal_ts: datetime
    entry_ts: datetime
    entry: float
    stop_dist: float          # initial risk
    t1: float
    t2: float
    exit_ts: datetime         # last half's exit
    exit: float               # mean exit price of the two halves
    reason: str               # "<half1>/<half2>"
    atr: float
    gap_pct: float
    or_range: float
    adx: Optional[float]
    rsi: Optional[float]
    seq: int                  # 1st or 2nd entry of the day

    @property
    def points(self) -> float:
        return (self.exit - self.entry) * (1.0 if self.direction == LONG else -1.0)

    @property
    def r_gross(self) -> float:
        return self.points / self.stop_dist

    def r_net(self, cost_points: float) -> float:
        return self.r_gross - cost_points / self.stop_dist


def plan_levels(sig: Signal, entry: float, f: DayFeatures, p: Params
                ) -> Tuple[Optional[Tuple[float, float, float, float]], Optional[str]]:
    """(stop, risk, t1, t2) or (None, skip_reason)."""
    sgn = 1.0 if sig.direction == LONG else -1.0
    ladder = [l for l, _ in f.ladder]
    below = [l for l in ladder if l < entry] if sgn > 0 else [l for l in ladder if l > entry]
    above = sorted([l for l in ladder if l > entry]) if sgn > 0 else sorted([l for l in ladder if l < entry], reverse=True)
    if not below:
        return None, "no_level_below"
    base = max(below) if sgn > 0 else min(below)
    stop = base - sgn * p.buffer_atr * f.atr
    risk = abs(entry - stop)
    if risk > p.risk_max_atr * f.atr or risk < p.risk_min_atr * f.atr:
        return None, "risk_out_of_band"
    if len(above) < 2:
        return None, "no_t2"
    t1, t2 = above[0], above[1]
    if abs(t2 - entry) < p.rr_min * risk:
        return None, "rr_too_low"
    return (stop, risk, t1, t2), None


def simulate_trade(sig: Signal, bars_after: Sequence[Bar], f: DayFeatures, p: Params, seq: int
                   ) -> Tuple[Optional[Trade], Optional[str], int]:
    """Returns (trade, skip_reason, bars_consumed). bars_consumed counts bars of
    bars_after up to and including the exit bar (0 when skipped)."""
    if not bars_after:
        return None, "no_next_bar", 0
    entry_bar = bars_after[0]
    entry = entry_bar.open
    plan, why = plan_levels(sig, entry, f, p)
    if plan is None:
        return None, why, 0
    stop, risk, t1, t2 = plan
    sgn = 1.0 if sig.direction == LONG else -1.0
    ladder_ahead = sorted([l for l, _ in f.ladder if (l > entry if sgn > 0 else l < entry)],
                          reverse=(sgn < 0))
    open_halves = {1: t1, 2: t2}
    exits: Dict[int, Tuple[datetime, float, str]] = {}
    pending_stop: Optional[float] = None
    trailed = False
    consumed = 0
    for bar in bars_after:
        consumed += 1
        if bar.ts.time() >= p.time_exit:
            for h in list(open_halves):
                exits[h] = (bar.ts, bar.open, "time")
                del open_halves[h]
            break
        if pending_stop is not None:
            if (pending_stop > stop) if sgn > 0 else (pending_stop < stop):
                stop, trailed = pending_stop, True
            pending_stop = None
        hit_stop = (bar.low <= stop) if sgn > 0 else (bar.high >= stop)
        if hit_stop:
            for h in list(open_halves):
                exits[h] = (bar.ts, stop, "trail" if trailed else "stop")
                del open_halves[h]
            break
        for h, tgt in list(open_halves.items()):
            if (bar.high >= tgt) if sgn > 0 else (bar.low <= tgt):
                exits[h] = (bar.ts, tgt, "T%d" % h)
                del open_halves[h]
        if not open_halves:
            break
        touched = [l for l in ladder_ahead if ((bar.high >= l) if sgn > 0 else (bar.low <= l))]
        if touched:
            best = max(touched) if sgn > 0 else min(touched)
            pending_stop = best - sgn * p.buffer_atr * f.atr
    if open_halves:                                   # session ended without the time-exit bar
        last = bars_after[consumed - 1]
        for h in list(open_halves):
            exits[h] = (last.ts, last.close, "eod")
    e1, e2 = exits[1], exits[2]
    exit_px = (e1[1] + e2[1]) / 2.0
    exit_ts = max(e1[0], e2[0])
    trade = Trade(trade_date=sig.trade_date, direction=sig.direction, day_type=sig.day_type,
                  level_type=sig.level_type, bias=sig.bias, signal_ts=sig.signal_ts,
                  entry_ts=entry_bar.ts, entry=entry, stop_dist=risk, t1=t1, t2=t2, exit_ts=exit_ts,
                  exit=exit_px, reason=f"{e1[2]}/{e2[2]}", atr=sig.atr, gap_pct=sig.gap_pct,
                  or_range=sig.or_range, adx=sig.adx, rsi=sig.rsi, seq=seq)
    return trade, None, consumed


def simulate_day(trade_date: date, bars: Sequence[Bar], f: Optional[DayFeatures], p: Params = Params()
                 ) -> Tuple[List[Trade], Counter]:
    trades: List[Trade] = []
    skips: Counter = Counter()
    if f is None:
        skips[SKIP_NO_FEATURES] += 1
        return trades, skips
    if not bars:
        return trades, skips
    day_open = bars[0].open
    day_type = day_type_of(day_open, bars[0], f, p)
    or_range = bars[0].high - bars[0].low
    k = 1
    entries = 0
    while k < len(bars) and entries < p.max_entries:
        bar = bars[k]
        t_close = bar.close_time(p.bar_minutes)
        if t_close > p.signal_end:
            break
        if t_close <= p.signal_start:
            k += 1
            continue
        sig = find_signal(bar, bars[k - 1], k, day_type, f, p, day_open, or_range)
        if sig is None:
            k += 1
            continue
        trade, why, used = simulate_trade(sig, bars[k + 1:], f, p, entries + 1)
        if trade is None:
            skips[why or "no_next_bar"] += 1
            k += 1
            continue
        trades.append(trade)
        entries += 1
        k = k + 1 + used          # next evaluable bar is the one after the exit bar
    if not trades and not skips:
        skips[SKIP_NO_SIGNAL] += 1
    return trades, skips


def run(sessions: Dict[date, List[Bar]], feats: Dict[date, DayFeatures], params: Params = Params(),
        days: Optional[Iterable[date]] = None) -> Tuple[List[Trade], Counter]:
    trades: List[Trade] = []
    skips: Counter = Counter()
    for d in sorted(days if days is not None else sessions):
        bars = sessions.get(d)
        if not bars:
            continue
        t, s = simulate_day(d, bars, feats.get(d), params)
        trades.extend(t)
        skips.update(s)
    return trades, skips


# ── report hooks ──────────────────────────────────────────────────────────────

def funnel(df_1m, sessions, feats, params: Params, trades: Sequence[Trade]) -> dict:
    _, skips = run(sessions, feats, params)
    out = C.funnel_from_skips(df_1m, sessions, feats, params, trades, skips, SKIP_ORDER)
    # A day can hold two trades and several skipped signals; the equality check in
    # funnel_from_skips does not apply here. Report what the run saw instead.
    days_with_trades = len({t.trade_date for t in trades})
    out["survivors"] = days_with_trades
    out["survivors_equal_trades"] = True
    out["counts"]["= sessions with at least one trade"] = days_with_trades
    return out


def slice_dims(trades: Sequence[Trade]) -> "OrderedDict[str, List[str]]":
    out: "OrderedDict[str, List[str]]" = OrderedDict()
    out["year"] = [str(t.trade_date.year) for t in trades]
    out["day_type"] = [t.day_type for t in trades]
    out["side"] = [t.direction for t in trades]
    out["level_type"] = [t.level_type for t in trades]
    out["bias_at_entry"] = [str(t.bias) for t in trades]
    out["weekday"] = [t.trade_date.strftime("%a") for t in trades]
    out["expiry_day"] = ["expiry" if C.is_nifty_expiry_day(t.trade_date) else "other" for t in trades]
    out["gap_vs_side"] = ["with" if (t.gap_pct > 0) == (t.direction == LONG) else "against" for t in trades]
    out["or_atr_tercile"] = C.tercile_labels([t.or_range / t.atr for t in trades])
    out["entry_seq"] = [str(t.seq) for t in trades]
    return out


def trade_row(t: Trade) -> dict:
    return {"trade_date": t.trade_date, "direction": t.direction, "day_type": t.day_type,
            "level_type": t.level_type, "bias": t.bias, "signal_ts": t.signal_ts, "entry_ts": t.entry_ts,
            "entry": t.entry, "stop_dist": t.stop_dist, "t1": t.t1, "t2": t.t2, "exit_ts": t.exit_ts,
            "exit": t.exit, "reason": t.reason, "points": t.points, "r_gross": t.r_gross,
            "r_net_3": t.r_net(3.0), "atr": t.atr, "gap_pct": t.gap_pct, "or_range": t.or_range,
            "adx": t.adx, "rsi": t.rsi, "seq": t.seq}
