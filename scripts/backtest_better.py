#!/usr/bin/env python3
"""
scripts/backtest_better.py — do the "better strategy" ideas actually beat the
base detectors? Two experiments on the historical 5m candles:

  A) REGIME FILTER — re-run ORB / VWAP_TREND / VWAP_REV but only accept a signal
     that is (i) trend-aligned (long above VWAP / short below), (ii) inside the
     09:45–14:00 window, and (iii) has enough volatility (ATR% floor). Compare
     filtered vs unfiltered.

  B) RELATIVE STRENGTH — cross-sectional: each bar rank the universe by return
     since the open, then measure the next-bar spread of long-top-K vs
     short-bottom-K (momentum) and its reverse (mean-reversion).

Usage:
  python scripts/backtest_better.py --months 12
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import numpy as np
import psycopg2

from signals.config import SignalConfig
from signals.detectors import (detect_orb, detect_vwap_trend, detect_vwap_reversal,
                               LONG, SHORT)
from signals.backtest import backtest_all, stats

SESSION_START, SESSION_END = time(9, 15), time(15, 35)
UNIVERSE = [
    "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "TCS", "INFY",
    "HCLTECH", "WIPRO", "TECHM", "RELIANCE", "ONGC", "NTPC", "POWERGRID",
    "TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "VEDL", "ADANIPORTS", "LT", "ITC", "BHARTIARTL", "BAJFINANCE",
]

FILTER_START, FILTER_END = time(9, 45), time(14, 0)
ATR_PCT_FLOOR = 0.0010          # 0.10% ATR/price minimum


def load_days(cur, symbol, interval, since):
    cur.execute('SELECT ts, open, high, low, close, volume FROM candles '
                'WHERE symbol=%s AND "interval"=%s AND ts>=%s ORDER BY ts',
                (symbol, interval, since))
    days = defaultdict(list)
    for ts, o, h, l, c, v in cur.fetchall():
        if SESSION_START <= ts.time() <= SESSION_END:
            days[ts.date()].append({"ts": ts.replace(tzinfo=None), "open": float(o),
                "high": float(h), "low": float(l), "close": float(c), "volume": float(v or 0)})
    return days


def make_filtered(detector):
    """Wrap a detector: keep the signal only if trend-aligned, in the entry
    window, and above the ATR% floor."""
    def wrapped(s):
        sig = detector(s)
        if sig is None:
            return None
        if sig.direction == LONG and sig.trigger_price <= sig.vwap:
            return None
        if sig.direction == SHORT and sig.trigger_price >= sig.vwap:
            return None
        t = sig.ts.time()
        if not (FILTER_START <= t <= FILTER_END):
            return None
        if not (sig.atr == sig.atr and sig.trigger_price > 0):
            return None
        if sig.atr / sig.trigger_price < ATR_PCT_FLOOR:
            return None
        return sig
    wrapped.__name__ = detector.__name__ + "_filtered"
    return wrapped


def run_regime_experiment(cur, cfg, since, sl_atr, tp_atr):
    base = [detect_orb, detect_vwap_trend, detect_vwap_reversal]
    filt = [make_filtered(d) for d in base]
    agg_base, agg_filt = defaultdict(list), defaultdict(list)
    for sym in UNIVERSE:
        days = load_days(cur, sym, "5m", since)
        if not days:
            continue
        for strat, tr in backtest_all(sym, base, days, cfg, sl_atr, tp_atr).items():
            agg_base[strat].extend(tr)
        for strat, tr in backtest_all(sym, filt, days, cfg, sl_atr, tp_atr).items():
            agg_filt[strat].extend(tr)

    print("\n=== A) REGIME FILTER — base vs filtered (trend-align + 09:45–14:00 + ATR% floor) ===")
    print(f"{'STRATEGY':<12} {'VARIANT':<9} {'TRADES':>7} {'WIN%':>6} {'AVG%':>7} {'TOTAL%':>9} {'PF':>6}")
    print("-" * 62)
    for strat in ("ORB", "VWAP_TREND", "VWAP_REV"):
        for label, agg in (("base", agg_base), ("filtered", agg_filt)):
            s = stats(agg.get(strat, []))
            pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
            print(f"{strat:<12} {label:<9} {s['trades']:>7} {s['win_rate']:>5.1f} "
                  f"{s['avg_pnl']:>7.3f} {s['total_pnl']:>9.1f} {pf:>6}")


def run_relative_strength(cur, since, top_k=5, warmup=6):
    # Load aligned close series per symbol per day.
    per_day = defaultdict(dict)      # date -> {symbol: [(ts, close)]}
    for sym in UNIVERSE:
        for d, bars in load_days(cur, sym, "5m", since).items():
            per_day[d][sym] = [(b["ts"], b["close"]) for b in bars]

    mom_spreads, rev_spreads = [], []
    for d, symmap in per_day.items():
        # align on the common bar timestamps present for most symbols
        # build matrix using the min length across symbols with >= warmup+2 bars
        series = {s: v for s, v in symmap.items() if len(v) >= warmup + 2}
        if len(series) < top_k * 2 + 2:
            continue
        n = min(len(v) for v in series.values())
        syms = list(series.keys())
        closes = np.array([[series[s][i][1] for i in range(n)] for s in syms])  # [S, n]
        opens = closes[:, 0][:, None]
        ret_from_open = closes / opens - 1.0                                    # [S, n]
        nxt = closes[:, 1:] / closes[:, :-1] - 1.0                              # [S, n-1]
        for t in range(warmup, n - 1):
            order = np.argsort(ret_from_open[:, t])
            bottom = order[:top_k]; top = order[-top_k:]
            long_mom = nxt[top, t].mean() - nxt[bottom, t].mean()      # long strong, short weak
            mom_spreads.append(long_mom * 100.0)
            rev_spreads.append(-long_mom * 100.0)                      # reverse

    def rs_stats(x, label):
        if not x:
            print(f"{label:<28} no data"); return
        a = np.array(x)
        sharpe = a.mean() / a.std() * np.sqrt(len(a)) if a.std() > 0 else 0
        print(f"{label:<28} bars={len(a):>6}  avg%/bar={a.mean():>8.4f}  "
              f"total%={a.sum():>9.1f}  hit%={(a > 0).mean() * 100:>5.1f}  sharpe={sharpe:>6.1f}")

    print(f"\n=== B) RELATIVE STRENGTH — long top {top_k} / short bottom {top_k}, next-bar spread ===")
    rs_stats(mom_spreads, "momentum (long strong)")
    rs_stats(rev_spreads, "reversal (long weak)")
    print("(spread = mean next-bar return of longs minus shorts, per rebalance bar; costs not modelled)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--sl-atr", type=float, default=1.5)
    ap.add_argument("--tp-atr", type=float, default=2.0)
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    cfg = SignalConfig()
    since = datetime.now() - timedelta(days=int(args.months * 30.5))
    conn = psycopg2.connect(os.environ["DB_URL"]); cur = conn.cursor()
    print(f"Universe {len(UNIVERSE)} symbols · 5m · {args.months}mo")
    run_regime_experiment(cur, cfg, since, args.sl_atr, args.tp_atr)
    run_relative_strength(cur, since, top_k=args.top_k)
    conn.close()


if __name__ == "__main__":
    main()
