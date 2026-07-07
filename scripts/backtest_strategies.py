#!/usr/bin/env python3
"""
scripts/backtest_strategies.py — validate the intraday signal detectors on the
historical candles in PostgreSQL.

Replays real 5m bars (session 09:15–15:30) for a universe of liquid large-caps
through the live detectors + an ATR stop/target simulation, then prints a ranked
performance table per strategy so we keep what actually holds up.

Usage:
  python scripts/backtest_strategies.py                       # 1y, default universe
  python scripts/backtest_strategies.py --months 6 --interval 5m
  python scripts/backtest_strategies.py --symbols NIFTY RELIANCE TCS
  python scripts/backtest_strategies.py --sl-atr 1.5 --tp-atr 2.5
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

import psycopg2

from signals.config import SignalConfig
from signals.detectors import DETECTORS
from signals.backtest import backtest_all, stats

SESSION_START = time(9, 15)
SESSION_END   = time(15, 35)

DEFAULT_UNIVERSE = [
    "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK",
    "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM",
    "RELIANCE", "ONGC", "NTPC", "POWERGRID",
    "TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO",
    "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL",
    "ADANIPORTS", "LT", "ITC", "BHARTIARTL", "BAJFINANCE",
]


def load_days(cur, symbol: str, interval: str, since: datetime) -> dict:
    """Return {trade_date: [bar dicts]} for regular-session bars, oldest first."""
    cur.execute(
        'SELECT ts, open, high, low, close, volume FROM candles '
        'WHERE symbol=%s AND "interval"=%s AND ts>=%s ORDER BY ts',
        (symbol, interval, since),
    )
    days = defaultdict(list)
    for ts, o, h, l, c, v in cur.fetchall():
        t = ts.time()
        if t < SESSION_START or t > SESSION_END:
            continue
        days[ts.date()].append({
            "ts": ts.replace(tzinfo=None), "open": float(o), "high": float(h),
            "low": float(l), "close": float(c), "volume": float(v or 0),
        })
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE)
    ap.add_argument("--sl-atr", type=float, default=1.5)
    ap.add_argument("--tp-atr", type=float, default=2.0)
    args = ap.parse_args()

    cfg = SignalConfig()
    cfg.bar_interval = args.interval
    since = datetime.now() - timedelta(days=int(args.months * 30.5))

    conn = psycopg2.connect(os.environ["DB_URL"])
    cur = conn.cursor()

    agg = defaultdict(list)   # strategy -> [Trade]
    print(f"Backtesting {len(args.symbols)} symbols · {args.interval} · "
          f"{args.months}mo · SL={args.sl_atr}ATR TP={args.tp_atr}ATR\n")
    for sym in args.symbols:
        days = load_days(cur, sym, args.interval, since)
        if not days:
            print(f"  {sym:12} no data — skip")
            continue
        by_strat = backtest_all(sym, list(DETECTORS), days, cfg,
                                sl_atr=args.sl_atr, tp_atr=args.tp_atr)
        ntr = sum(len(v) for v in by_strat.values())
        print(f"  {sym:12} {len(days):>4} days · {ntr:>4} trades")
        for strat, trades in by_strat.items():
            agg[strat].extend(trades)
    conn.close()

    rows = []
    for strat, trades in agg.items():
        s = stats(trades)
        rows.append((strat, s))
    rows.sort(key=lambda r: r[1]["total_pnl"], reverse=True)

    print("\n" + "=" * 92)
    print(f"{'STRATEGY':<12} {'TRADES':>7} {'WIN%':>6} {'AVG%':>7} {'TOTAL%':>9} "
          f"{'PF':>6} {'MAXDD%':>8} {'SHARPE':>7} {'EXPECT%':>8}")
    print("-" * 92)
    for strat, s in rows:
        pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
        print(f"{strat:<12} {s['trades']:>7} {s['win_rate']:>5.1f} {s['avg_pnl']:>7.3f} "
              f"{s['total_pnl']:>9.1f} {pf:>6} {s['max_dd']:>8.1f} "
              f"{s['sharpe']:>7.1f} {s['avg_pnl']:>8.3f}")
    print("=" * 92)
    print("AVG%/EXPECT% = mean P&L per trade · TOTAL% = summed P&L · PF = profit factor · "
          "gross costs NOT modelled.")


if __name__ == "__main__":
    main()
