"""
signals/backtest.py — event-driven intraday backtester for the signal detectors.

Replays historical OHLCV bars through the SAME SymbolSession + detector code the
live engine uses (so a backtest matches live behaviour), then simulates each
entry with an ATR-based stop-loss / target and an end-of-day square-off. Pure —
no DB or network; callers pass in bars grouped by trading day.

Trade model (one position per symbol/strategy at a time, matching the live
one-signal-per-(day,symbol,strategy,direction) dedup):
  • entry  = the signal bar's close (trigger_price)
  • stop   = entry ∓ sl_atr · ATR      (below for long, above for short)
  • target = entry ± tp_atr · ATR
  • exits when a later bar's range touches stop/target (stop assumed first if a
    single bar spans both — conservative), else at the day's last bar (EOD).
"""

from dataclasses import dataclass
from datetime import date
from statistics import pstdev
from typing import Callable, Dict, List, Optional

from .config import SignalConfig
from .detectors import LONG
from .session import SymbolSession


@dataclass
class Trade:
    trade_date: date
    strategy: str
    direction: str
    entry: float
    exit: float
    pnl_pct: float
    reason: str        # 'SL' | 'TP' | 'EOD'
    bars_held: int


def _manage(bars: List[dict], idx: int, direction: str, entry: float, atr: float,
            sl_atr: float, tp_atr: float) -> tuple:
    """Walk bars forward from the entry, returning (exit_idx, exit_price, reason)."""
    if direction == LONG:
        stop, target = entry - sl_atr * atr, entry + tp_atr * atr
    else:
        stop, target = entry + sl_atr * atr, entry - tp_atr * atr
    last = len(bars) - 1
    for j in range(idx + 1, last + 1):
        hi, lo = bars[j]["high"], bars[j]["low"]
        if direction == LONG:
            if lo <= stop:   return j, stop,   "SL"
            if hi >= target: return j, target, "TP"
        else:
            if hi >= stop:   return j, stop,   "SL"
            if lo <= target: return j, target, "TP"
    return last, bars[last]["close"], "EOD"   # square-off at session end


def simulate_day(symbol: str, detector: Callable, bars: List[dict],
                 cfg: SignalConfig, trade_date: date,
                 sl_atr: float, tp_atr: float) -> List[Trade]:
    """Replay one trading day: detect on each closed bar, then trade sequentially
    (no overlapping positions for the same detector)."""
    sess = SymbolSession(symbol=symbol, cfg=cfg, trade_date=trade_date)
    entries: List[tuple] = []            # (bar_idx, direction, entry_price, atr)
    seen = set()
    for idx, bar in enumerate(bars):
        sess.add_bar(bar)
        sig = detector(sess)
        if sig is None:
            continue
        key = (sig.strategy, sig.direction)
        if key in seen:
            continue
        seen.add(key)
        entries.append((idx, sig.direction, sig.trigger_price, sig.atr, sig.strategy))

    trades: List[Trade] = []
    next_free = 0
    for idx, direction, entry, atr, strat in entries:
        if idx < next_free:
            continue
        if not (atr == atr and atr > 0):      # ATR must be finite/positive
            continue
        exit_idx, exit_price, reason = _manage(bars, idx, direction, entry, atr,
                                               sl_atr, tp_atr)
        pnl = ((exit_price - entry) / entry if direction == LONG
               else (entry - exit_price) / entry)
        trades.append(Trade(trade_date, strat, direction, entry, exit_price,
                            pnl * 100.0, reason, exit_idx - idx))
        next_free = exit_idx + 1
    return trades


def backtest(symbol: str, detector: Callable, days: Dict[date, List[dict]],
             cfg: SignalConfig, sl_atr: float = 1.5, tp_atr: float = 2.0) -> List[Trade]:
    """Run a detector over many trading days for one symbol."""
    out: List[Trade] = []
    for d, bars in days.items():
        if len(bars) < cfg.warmup_bars + 2:
            continue
        out.extend(simulate_day(symbol, detector, bars, cfg, d, sl_atr, tp_atr))
    return out


def simulate_day_multi(symbol: str, detectors: List[Callable], bars: List[dict],
                       cfg: SignalConfig, trade_date: date,
                       sl_atr: float, tp_atr: float) -> Dict[str, List[Trade]]:
    """Replay a day ONCE for all detectors (they share the session's cached
    indicators — the indicators are causal, so a full-array value at bar i equals
    the incremental value). Returns trades grouped by strategy name."""
    sess = SymbolSession(symbol=symbol, cfg=cfg, trade_date=trade_date)
    entries: Dict[str, list] = {}
    seen = set()
    for idx, bar in enumerate(bars):
        sess.add_bar(bar)
        for det in detectors:
            sig = det(sess)
            if sig is None:
                continue
            key = (sig.strategy, sig.direction)
            if key in seen:
                continue
            seen.add(key)
            entries.setdefault(sig.strategy, []).append(
                (idx, sig.direction, sig.trigger_price, sig.atr))

    out: Dict[str, List[Trade]] = {}
    for strat, elist in entries.items():
        trades: List[Trade] = []
        next_free = 0
        for idx, direction, entry, atr in elist:
            if idx < next_free or not (atr == atr and atr > 0):
                continue
            ei, ep, reason = _manage(bars, idx, direction, entry, atr, sl_atr, tp_atr)
            pnl = ((ep - entry) / entry if direction == LONG else (entry - ep) / entry)
            trades.append(Trade(trade_date, strat, direction, entry, ep,
                               pnl * 100.0, reason, ei - idx))
            next_free = ei + 1
        out[strat] = trades
    return out


def backtest_all(symbol: str, detectors: List[Callable],
                 days: Dict[date, List[dict]], cfg: SignalConfig,
                 sl_atr: float = 1.5, tp_atr: float = 2.0) -> Dict[str, List[Trade]]:
    """Run all detectors over many days for one symbol; merge by strategy."""
    merged: Dict[str, List[Trade]] = {}
    for d, bars in days.items():
        if len(bars) < cfg.warmup_bars + 2:
            continue
        for strat, trades in simulate_day_multi(
                symbol, detectors, bars, cfg, d, sl_atr, tp_atr).items():
            merged.setdefault(strat, []).extend(trades)
    return merged


def stats(trades: List[Trade]) -> dict:
    """Aggregate performance metrics from a list of trades."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "win_rate": 0.0, "avg_pnl": 0.0, "total_pnl": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
                "max_dd": 0.0, "sharpe": 0.0}
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = sum(pnls)
    avg = total / n
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    # max drawdown on the cumulative per-trade equity curve
    cum = peak = mdd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    sd = pstdev(pnls) if n > 1 else 0.0
    sharpe = (avg / sd) * (n ** 0.5) if sd > 0 else 0.0   # per-run, trade-count scaled
    return {
        "trades": n,
        "win_rate": len(wins) / n * 100.0,
        "avg_pnl": avg,
        "total_pnl": total,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "profit_factor": pf,
        "max_dd": mdd,
        "sharpe": sharpe,
    }
