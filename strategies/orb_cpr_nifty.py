"""
strategies/orb_cpr_nifty.py — "ORB-CPR-15" on NIFTY 50. Pure functions, no I/O.

Single source of truth for the signal: the backtest (`strategies.backtest`)
and the live runner both drive `DayState.on_bar()` with 5-minute bars.

Per session, from the PREVIOUS valid session's daily O/H/L/C (no lookahead):
    pivot P = (H+L+C)/3,  BC = (H+L)/2,  TC = 2P-BC   (CPR top = max, bottom = min)
    CPR width % = |TC-BC| / C * 100
    ATR(14), Wilder smoothing, as of the previous close.
Special sessions (Muhurat, Saturday sessions, anything under `min_session_bars`
five-minute bars) are dropped from both the feature series and trading.

Trade rules (all in `Params`):
    opening range = high/low of the first `or_minutes` (09:15-09:30) from 5m bars
    skip the day if  |open - prev close| > gap_atr_max*ATR
                  or OR range < or_min_atr*ATR  or OR range > or_max_atr*ATR
                  or CPR width % > cpr_max_pct
    LONG : a 5m bar closes above ORH and above CPR top, bar close in (09:30, 11:00]
    SHORT: a 5m bar closes below ORL and below CPR bottom, same window
    one signal per day; entry = open of the NEXT 5m bar
    S = min(OR range, stop_atr_cap*ATR); target = entry +/- target_r*S
    after +be_trigger_r*S the stop moves to entry, effective from the next bar
    time exit at `time_exit`; stop and target in one bar => stop first
    cost (backtest) = cost_points round trip, in R = cost_points / S

Instrument mapping for the alert: ATM debit vertical (`plan_spread`).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

STRATEGY = "ORB_CPR_15"
LONG = "LONG"
SHORT = "SHORT"

# skip / exit reasons (stable strings: they are journaled and reported)
SKIP_GAP = "gap_too_large"
SKIP_OR_SMALL = "or_too_small"
SKIP_OR_LARGE = "or_too_large"
SKIP_CPR_WIDE = "cpr_too_wide"
SKIP_NO_FEATURES = "no_features"
SKIP_NO_BREAKOUT = "no_breakout"
EXIT_STOP = "stop"
EXIT_BE_STOP = "be_stop"
EXIT_TARGET = "target"
EXIT_TIME = "time"
EXIT_EOD = "eod"


# ── Parameters ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Params:
    bar_minutes: int = 5
    or_minutes: int = 15
    session_open: time = time(9, 15)
    signal_start: time = time(9, 30)      # earliest eligible bar CLOSE (exclusive)
    signal_end: time = time(11, 0)        # latest eligible bar CLOSE (inclusive)
    time_exit: time = time(15, 15)        # exit at the open of this bar
    atr_period: int = 14
    gap_atr_max: float = 1.0
    or_min_atr: float = 0.20
    or_max_atr: float = 0.60
    cpr_max_pct: float = 0.6
    stop_atr_cap: float = 0.5
    target_r: float = 1.5
    be_trigger_r: float = 1.0
    cost_points: float = 3.0
    min_session_bars: int = 70            # five-minute bars; a full session has 75
    max_chase_atr: float = 0.10           # alert only: do not chase beyond entry + this

    @property
    def or_end(self) -> time:
        return _add_minutes(self.session_open, self.or_minutes)


def _add_minutes(t: time, minutes: int) -> time:
    return (datetime.combine(date(2000, 1, 1), t) + timedelta(minutes=minutes)).time()


# ── Bars ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bar:
    ts: datetime          # bar OPEN time (naive, IST)
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def close_time(self, bar_minutes: int) -> time:
        return (self.ts + timedelta(minutes=bar_minutes)).time()


def resample_5m(df_1m: pd.DataFrame, params: Params = Params()) -> pd.DataFrame:
    """1-minute bars (columns ts, open, high, low, close, volume; ts tz-aware or
    naive IST) -> 5-minute bars anchored at 09:15, labelled by bar open time
    (naive IST). Buckets opening at/after 15:30 are dropped."""
    if df_1m.empty:
        return df_1m.iloc[0:0]
    df = df_1m.copy()
    ts = pd.to_datetime(df["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df["ts"] = ts
    df = df.sort_values("ts")
    day = df["ts"].dt.normalize()
    anchor = day + pd.Timedelta(hours=params.session_open.hour, minutes=params.session_open.minute)
    offset_min = ((df["ts"] - anchor).dt.total_seconds() // 60)
    bucket = anchor + pd.to_timedelta((offset_min // params.bar_minutes) * params.bar_minutes, unit="m")
    df["bucket"] = bucket
    df = df[(offset_min >= 0) & (df["bucket"].dt.time < time(15, 30))]
    out = df.groupby("bucket").agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   volume=("volume", "sum")).reset_index()
    out = out.rename(columns={"bucket": "ts"})
    for c in ("open", "high", "low", "close"):
        out[c] = out[c].astype(float)
    out["volume"] = out["volume"].astype("int64")
    return out


def split_sessions(df_5m: pd.DataFrame, params: Params = Params()) -> Dict[date, List[Bar]]:
    """5m bars -> {trade_date: [Bar...]} keeping only sessions with at least
    `min_session_bars` bars (special/partial sessions are dropped entirely)."""
    out: Dict[date, List[Bar]] = {}
    if df_5m.empty:
        return out
    ts = pd.to_datetime(df_5m["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df = df_5m.assign(ts=ts).sort_values("ts")
    for d, g in df.groupby(df["ts"].dt.date):
        if len(g) < params.min_session_bars:
            continue
        out[d] = [Bar(r.ts.to_pydatetime(), float(r.open), float(r.high), float(r.low),
                      float(r.close), int(r.volume)) for r in g.itertuples(index=False)]
    return out


# ── Daily features (no lookahead) ─────────────────────────────────────────────

@dataclass(frozen=True)
class DayFeatures:
    trade_date: date
    prev_date: date
    prev_open: float
    prev_high: float
    prev_low: float
    prev_close: float
    pivot: float
    cpr_top: float
    cpr_bottom: float
    cpr_width_pct: float
    atr: float


def cpr(h: float, l: float, c: float) -> Tuple[float, float, float, float]:
    """(pivot, top, bottom, width %) of the floor-pivot Central Pivot Range."""
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = 2.0 * p - bc
    top, bottom = max(tc, bc), min(tc, bc)
    width = abs(tc - bc) / c * 100.0 if c else float("nan")
    return p, top, bottom, width


def atr_wilder(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               period: int) -> List[Optional[float]]:
    """Wilder ATR per element, None until `period` true ranges exist. Element i
    uses bars 0..i inclusive, so atrs[i] is the ATR 'as of' close i."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n == 0:
        return out
    trs: List[float] = []
    atr: Optional[float] = None
    for i in range(n):
        tr = highs[i] - lows[i] if i == 0 else max(
            highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
        if i + 1 < period:
            continue
        if atr is None:
            atr = sum(trs[-period:]) / period
        else:
            atr = (atr * (period - 1) + tr) / period
        out[i] = atr
    return out


def daily_features(sessions: Dict[date, List[Bar]], params: Params = Params()) -> Dict[date, DayFeatures]:
    """Features for each session t from sessions strictly before t (the previous
    VALID session's OHLC and the ATR as of its close). Sessions without enough
    history get no entry (the day is skipped as `no_features`)."""
    days = sorted(sessions)
    opens = [sessions[d][0].open for d in days]
    highs = [max(b.high for b in sessions[d]) for d in days]
    lows = [min(b.low for b in sessions[d]) for d in days]
    closes = [sessions[d][-1].close for d in days]
    atrs = atr_wilder(highs, lows, closes, params.atr_period)
    out: Dict[date, DayFeatures] = {}
    for i in range(1, len(days)):
        a = atrs[i - 1]
        if a is None or not math.isfinite(a) or a <= 0:
            continue
        p, top, bottom, width = cpr(highs[i - 1], lows[i - 1], closes[i - 1])
        out[days[i]] = DayFeatures(
            trade_date=days[i], prev_date=days[i - 1], prev_open=opens[i - 1],
            prev_high=highs[i - 1], prev_low=lows[i - 1], prev_close=closes[i - 1],
            pivot=p, cpr_top=top, cpr_bottom=bottom, cpr_width_pct=width, atr=a)
    return out


# ── Per-bar evaluation (shared by backtest and live) ──────────────────────────

@dataclass(frozen=True)
class Signal:
    trade_date: date
    direction: str
    signal_ts: datetime           # CLOSE time of the signal bar
    signal_close: float
    or_high: float
    or_low: float
    atr: float
    cpr_top: float
    cpr_bottom: float
    cpr_width_pct: float
    day_open: float
    prev_close: float
    stop_dist: float              # S

    @property
    def or_range(self) -> float:
        return self.or_high - self.or_low

    @property
    def gap_pct(self) -> float:
        return (self.day_open - self.prev_close) / self.prev_close * 100.0

    def levels(self, entry: float) -> Dict[str, float]:
        sgn = 1.0 if self.direction == LONG else -1.0
        return {"entry": entry, "stop": entry - sgn * self.stop_dist,
                "target": entry + sgn * self.stop_dist * self._p.target_r,
                "be_trigger": entry + sgn * self.stop_dist * self._p.be_trigger_r}

    # params are attached by DayState so `levels` can be computed without re-passing
    _p: Params = field(default=Params(), compare=False, repr=False)


class DayState:
    """One session's evaluation state. Feed every 5m bar in order to `on_bar`;
    it returns the Signal exactly once (or never) and records `skip_reason`
    when a filter blocks the day. `decided` is True once either happened."""

    def __init__(self, trade_date: date, feats: Optional[DayFeatures], params: Params = Params()):
        self.trade_date = trade_date
        self.feats = feats
        self.p = params
        self.day_open: Optional[float] = None
        self.or_high = -math.inf
        self.or_low = math.inf
        self.or_bars = 0
        self.or_done = False
        self.skip_reason: Optional[str] = None
        self.signal: Optional[Signal] = None
        self.filters: Dict[str, bool] = {}

    @property
    def decided(self) -> bool:
        return self.signal is not None or self.skip_reason is not None

    @property
    def or_range(self) -> float:
        return self.or_high - self.or_low if self.or_done else float("nan")

    def _skip(self, reason: str) -> None:
        self.skip_reason = reason

    def _finish_or(self) -> None:
        self.or_done = True
        rng = self.or_high - self.or_low
        atr = self.feats.atr
        self.filters["or_min"] = rng >= self.p.or_min_atr * atr
        self.filters["or_max"] = rng <= self.p.or_max_atr * atr
        if not self.filters["or_min"]:
            self._skip(SKIP_OR_SMALL)
        elif not self.filters["or_max"]:
            self._skip(SKIP_OR_LARGE)

    def on_bar(self, bar: Bar) -> Optional[Signal]:
        if self.decided:
            return None
        if self.feats is None:
            self._skip(SKIP_NO_FEATURES)
            return None
        p, f = self.p, self.feats
        if self.day_open is None:
            self.day_open = bar.open
            self.filters["cpr"] = f.cpr_width_pct <= p.cpr_max_pct
            self.filters["gap"] = abs(bar.open - f.prev_close) <= p.gap_atr_max * f.atr
            if not self.filters["cpr"]:
                self._skip(SKIP_CPR_WIDE)
                return None
            if not self.filters["gap"]:
                self._skip(SKIP_GAP)
                return None
        t_open = bar.ts.time()
        t_close = bar.close_time(p.bar_minutes)
        if t_open < p.or_end:
            self.or_high = max(self.or_high, bar.high)
            self.or_low = min(self.or_low, bar.low)
            self.or_bars += 1
            if t_close >= p.or_end:
                self._finish_or()
            return None
        if not self.or_done:
            if self.or_bars == 0:            # the OR bars are missing: no basis to trade
                self._skip(SKIP_OR_SMALL)
                return None
            self._finish_or()
            if self.decided:
                return None
        if t_close > p.signal_end:
            self._skip(SKIP_NO_BREAKOUT)
            return None
        if t_close <= p.signal_start:
            return None
        direction = None
        if bar.close > self.or_high and bar.close > f.cpr_top:
            direction = LONG
        elif bar.close < self.or_low and bar.close < f.cpr_bottom:
            direction = SHORT
        if direction is None:
            return None
        s = min(self.or_high - self.or_low, p.stop_atr_cap * f.atr)
        self.signal = Signal(
            trade_date=self.trade_date, direction=direction,
            signal_ts=bar.ts + timedelta(minutes=p.bar_minutes), signal_close=bar.close,
            or_high=self.or_high, or_low=self.or_low, atr=f.atr, cpr_top=f.cpr_top,
            cpr_bottom=f.cpr_bottom, cpr_width_pct=f.cpr_width_pct, day_open=self.day_open,
            prev_close=f.prev_close, stop_dist=s, _p=p)
        return self.signal


# ── Trade simulation (backtest only) ──────────────────────────────────────────

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
    cpr_width_pct: float
    gap_pct: float

    @property
    def points(self) -> float:
        sgn = 1.0 if self.direction == LONG else -1.0
        return (self.exit - self.entry) * sgn

    @property
    def r_gross(self) -> float:
        return self.points / self.stop_dist

    def r_net(self, cost_points: float) -> float:
        return self.r_gross - cost_points / self.stop_dist


def simulate_trade(sig: Signal, bars_after: Sequence[Bar], params: Params = Params()) -> Optional[Trade]:
    """Fill at the open of the first bar after the signal bar and manage the
    position bar by bar. Returns None when there is no next bar."""
    if not bars_after:
        return None
    sgn = 1.0 if sig.direction == LONG else -1.0
    s = sig.stop_dist
    entry_bar = bars_after[0]
    entry = entry_bar.open
    stop = entry - sgn * s
    target = entry + sgn * s * params.target_r
    be_level = entry + sgn * s * params.be_trigger_r
    be_armed = False
    stop_is_be = False
    exit_px = exit_ts = reason = None
    last = entry_bar
    for bar in bars_after:
        last = bar
        if bar.ts.time() >= params.time_exit:
            exit_px, exit_ts, reason = bar.open, bar.ts, EXIT_TIME
            break
        if be_armed and not stop_is_be:              # BE reached on an earlier bar: effective now
            stop, stop_is_be = entry, True
        hit_stop = (bar.low <= stop) if sgn > 0 else (bar.high >= stop)
        hit_target = (bar.high >= target) if sgn > 0 else (bar.low <= target)
        if hit_stop:                                 # stop first when both fall in one bar
            exit_px, exit_ts, reason = stop, bar.ts, (EXIT_BE_STOP if stop_is_be else EXIT_STOP)
            break
        if hit_target:
            exit_px, exit_ts, reason = target, bar.ts, EXIT_TARGET
            break
        reached_be = (bar.high >= be_level) if sgn > 0 else (bar.low <= be_level)
        if reached_be:
            be_armed = True                          # stop moves to entry from the NEXT bar
    else:
        exit_px, exit_ts, reason = last.close, last.ts, EXIT_EOD
    return Trade(trade_date=sig.trade_date, direction=sig.direction, signal_ts=sig.signal_ts,
                 entry_ts=entry_bar.ts, entry=entry, stop_dist=s, exit_ts=exit_ts, exit=exit_px,
                 reason=reason, atr=sig.atr, or_range=sig.or_range,
                 cpr_width_pct=sig.cpr_width_pct, gap_pct=sig.gap_pct)


@dataclass
class DayResult:
    trade_date: date
    signal: Optional[Signal]
    trade: Optional[Trade]
    skip_reason: Optional[str]


def simulate_day(trade_date: date, bars: Sequence[Bar], feats: Optional[DayFeatures],
                 params: Params = Params()) -> DayResult:
    """Drive the shared evaluator over one session and simulate the trade."""
    state = DayState(trade_date, feats, params)
    for i, bar in enumerate(bars):
        sig = state.on_bar(bar)
        if sig is not None:
            trade = simulate_trade(sig, bars[i + 1:], params)
            return DayResult(trade_date, sig, trade, None if trade else "no_next_bar")
        if state.skip_reason is not None:
            return DayResult(trade_date, None, None, state.skip_reason)
    return DayResult(trade_date, None, None, state.skip_reason or SKIP_NO_BREAKOUT)


def run(sessions: Dict[date, List[Bar]], feats: Dict[date, DayFeatures],
        params: Params = Params(), days: Optional[Iterable[date]] = None) -> Tuple[List[Trade], Counter]:
    """Backtest over `days` (default: every session). Returns (trades, skip counts)."""
    trades: List[Trade] = []
    skips: Counter = Counter()
    for d in sorted(days if days is not None else sessions):
        bars = sessions.get(d)
        if not bars:
            continue
        res = simulate_day(d, bars, feats.get(d), params)
        if res.trade is not None:
            trades.append(res.trade)
        else:
            skips[res.skip_reason or SKIP_NO_BREAKOUT] += 1
    return trades, skips


# ── Statistics ────────────────────────────────────────────────────────────────

def r_series(trades: Sequence[Trade], cost_points: float) -> List[float]:
    return [t.r_net(cost_points) for t in trades]


def max_drawdown(rs: Sequence[float]) -> float:
    """Largest peak-to-trough fall of the cumulative R curve (>= 0)."""
    peak = cum = 0.0
    dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summarize(trades: Sequence[Trade], cost_points: float) -> dict:
    rs = r_series(trades, cost_points)
    n = len(rs)
    if n == 0:
        return {"n": 0, "avg_r": float("nan"), "win_rate": float("nan"), "total_r": 0.0,
                "max_dd_r": 0.0, "avg_points": float("nan"), "profit_factor": float("nan")}
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    pf = (sum(wins) / sum(losses)) if losses else float("inf")
    return {"n": n, "avg_r": sum(rs) / n, "win_rate": len(wins) / n, "total_r": sum(rs),
            "max_dd_r": max_drawdown(rs), "avg_points": sum(t.points for t in trades) / n,
            "profit_factor": pf}


def bootstrap_ci(rs: Sequence[float], n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 7) -> Tuple[float, float]:
    """Percentile bootstrap CI of the mean. Deterministic for a given seed."""
    import random
    if not rs:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(rs)
    means = sorted(sum(rng.choice(rs) for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(alpha / 2 * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return lo, hi


# ── Instrument mapping: ATM debit vertical ────────────────────────────────────

@dataclass(frozen=True)
class SpreadParams:
    width: int = 150                  # points between long and short strike (150-200)
    lot: int = 65                     # NIFTY lot size (config; warn if master differs)
    strike_step: int = 50
    stop_pct: float = 0.40            # premium stop = -40% of debit
    risk_cap_inr: float = 2300.0
    max_debit: float = 100.0
    min_sessions_to_expiry: int = 1   # on expiry day use the next weekly


@dataclass(frozen=True)
class SpreadPlan:
    direction: str
    right: str                        # CE | PE
    expiry: date
    atm: int
    long_strike: int
    short_strike: int
    long_bid: float
    long_ask: float
    short_bid: float
    short_ask: float
    debit: float                      # long ask - short bid (conservative)
    lot: int
    premium_stop: float               # debit * (1 - stop_pct): exit if spread value falls here
    risk_inr: float                   # stop_pct * debit * lot
    max_loss_inr: float               # debit * lot (held to expiry, both legs worthless)
    max_profit_inr: float             # (width - debit) * lot
    ok: bool
    reason: str


def atm_strike(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def plan_spread(direction: str, spot: float, expiry: date,
                quote: Callable[[int], Tuple[float, float]],
                sp: SpreadParams = SpreadParams()) -> SpreadPlan:
    """`quote(strike) -> (bid, ask)` for the option right implied by direction.
    LONG: buy ATM CE, sell CE at ATM+width. SHORT: buy ATM PE, sell PE at ATM-width."""
    atm = atm_strike(spot, sp.strike_step)
    right = "CE" if direction == LONG else "PE"
    short_strike = atm + sp.width if direction == LONG else atm - sp.width
    lb, la = quote(atm)
    sb, sa = quote(short_strike)
    debit = la - sb
    risk = sp.stop_pct * debit * sp.lot
    ok, reason = True, "OK"
    if debit <= 0 or not math.isfinite(debit):
        ok, reason = False, "NO TRADE: no usable quotes"
    elif risk > sp.risk_cap_inr or debit > sp.max_debit:
        ok, reason = False, "NO TRADE: spread too expensive"
    return SpreadPlan(direction=direction, right=right, expiry=expiry, atm=atm,
                      long_strike=atm, short_strike=short_strike, long_bid=lb, long_ask=la,
                      short_bid=sb, short_ask=sa, debit=debit, lot=sp.lot,
                      premium_stop=debit * (1.0 - sp.stop_pct), risk_inr=risk,
                      max_loss_inr=debit * sp.lot, max_profit_inr=(sp.width - debit) * sp.lot,
                      ok=ok, reason=reason)


# ── Calendar helpers ──────────────────────────────────────────────────────────

def is_trading_day(d: date, holidays: Iterable[date] = ()) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def sessions_until(d0: date, d1: date, holidays: Iterable[date] = ()) -> int:
    """Trading sessions after d0 up to and including d1 (0 when d1 <= d0)."""
    hs = set(holidays)
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if is_trading_day(d, hs):
            n += 1
    return n


def pick_expiry(today: date, listed: Iterable[date], min_sessions: int = 1,
                holidays: Iterable[date] = ()) -> Optional[date]:
    """Nearest listed expiry at least `min_sessions` sessions away (so an
    expiry-day signal rolls to the next weekly)."""
    for e in sorted(set(listed)):
        if e >= today and sessions_until(today, e, holidays) >= min_sessions:
            return e
    return None


# ── Alert formatting ──────────────────────────────────────────────────────────

def format_alert(sig: Signal, entry_ref: float, plan: Optional[SpreadPlan],
                 params: Params = Params(), filters: Optional[Dict[str, bool]] = None) -> str:
    """Monospace Telegram block. `entry_ref` = open of the bar after the signal."""
    lv = sig.levels(entry_ref)
    chase = params.max_chase_atr * sig.atr
    passed = ", ".join(k for k, v in (filters or {}).items() if v) or "-"
    lines = [
        f"ORB-CPR-15 | NIFTY | {sig.direction} | {sig.signal_ts.strftime('%H:%M')}",
        f"OR  {sig.or_low:.2f} - {sig.or_high:.2f} (rng {sig.or_range:.1f})",
        f"ATR {sig.atr:.1f}  CPR {sig.cpr_width_pct:.2f}%  gap {sig.gap_pct:+.2f}%",
        f"filters passed: {passed}",
        "",
        f"entry ref {lv['entry']:.2f} (next bar open; chase <= {lv['entry'] + (chase if sig.direction == LONG else -chase):.2f})",
        f"stop  {lv['stop']:.2f}  (S = {sig.stop_dist:.1f})",
        f"target {lv['target']:.2f}  (+{params.target_r:.1f}R)",
        f"BE trigger {lv['be_trigger']:.2f}  time exit {params.time_exit.strftime('%H:%M')}",
    ]
    if plan is not None:
        lines += [
            "",
            f"{'BUY ' + plan.right if plan.ok else plan.reason}",
            f"buy  {plan.long_strike} {plan.right} {plan.expiry:%d-%b}  bid/ask {plan.long_bid:.2f}/{plan.long_ask:.2f}",
            f"sell {plan.short_strike} {plan.right} {plan.expiry:%d-%b}  bid/ask {plan.short_bid:.2f}/{plan.short_ask:.2f}",
            f"debit {plan.debit:.2f} x {plan.lot} = Rs {plan.debit * plan.lot:,.0f}",
            f"premium stop {plan.premium_stop:.2f}  risk Rs {plan.risk_inr:,.0f}",
            f"max loss to expiry Rs {plan.max_loss_inr:,.0f}  max profit Rs {plan.max_profit_inr:,.0f}",
        ]
    return "\n".join(lines)


def format_skip(trade_date: date, reason: str) -> str:
    return f"ORB-CPR-15 | NIFTY | SKIP {trade_date:%d-%b} | {reason}"
