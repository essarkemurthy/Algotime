#!/usr/bin/env python3
"""
scripts/algo_eval.py — evaluate persisted algo paper-trading results.

Reads the paper_trades / paper_signal_decisions tables (populated live by the
algo) and prints a performance report over a window — the tool for the 90-day
real-time test.

Usage:
  python scripts/algo_eval.py                 # last 90 days
  python scripts/algo_eval.py --days 30
  python scripts/algo_eval.py --from 2026-07-01 --to 2026-09-30
"""
import os, sys, argparse
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import psycopg2


def _fmt(n):
    return f"{n:>+12,.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--to", dest="to", default=None)
    args = ap.parse_args()

    to_d = date.fromisoformat(args.to) if args.to else date.today()
    frm_d = date.fromisoformat(args.frm) if args.frm else to_d - timedelta(days=args.days)

    conn = psycopg2.connect(os.environ["DB_URL"]); cur = conn.cursor()
    W = "trade_date BETWEEN %s AND %s"
    P = (frm_d, to_d)

    cur.execute(f"SELECT COUNT(*), COALESCE(SUM(pnl),0), COUNT(*) FILTER (WHERE pnl>0), "
                f"COUNT(*) FILTER (WHERE pnl<0), COUNT(DISTINCT trade_date) "
                f"FROM paper_trades WHERE {W}", P)
    n, gross, wins, losses, days = cur.fetchone()
    gross = float(gross)

    print("=" * 68)
    print(f"ALGO PAPER-TRADING EVALUATION   {frm_d} -> {to_d}   ({days} trading days)")
    print("=" * 68)
    if not n:
        print("No trades in this window yet. Keep the algo running daily.")
        conn.close(); return

    cur.execute(f"SELECT COALESCE(AVG(pnl) FILTER (WHERE pnl>0),0), "
                f"COALESCE(AVG(pnl) FILTER (WHERE pnl<0),0), "
                f"COALESCE(SUM(pnl) FILTER (WHERE pnl>0),0), "
                f"COALESCE(SUM(pnl) FILTER (WHERE pnl<0),0) FROM paper_trades WHERE {W}", P)
    avg_win, avg_loss, sum_win, sum_loss = [float(x) for x in cur.fetchone()]
    pf = (sum_win / -sum_loss) if sum_loss else float("inf")

    print(f"Trades         : {n}   ({wins} win / {losses} loss   win-rate {wins/n*100:.1f}%)")
    print(f"Net P&L        : {_fmt(gross)}   (avg {_fmt(gross/n).strip()}/trade, {_fmt(gross/max(days,1)).strip()}/day)")
    print(f"Avg win / loss : {_fmt(avg_win)} / {_fmt(avg_loss)}   profit-factor {pf:.2f}")

    print("\nBy outcome:")
    cur.execute(f"SELECT reason, COUNT(*), COALESCE(SUM(pnl),0) FROM paper_trades WHERE {W} "
                f"GROUP BY reason ORDER BY 2 DESC", P)
    for reason, cnt, p in cur.fetchall():
        print(f"  {reason or '—':<12} {cnt:>4}   {_fmt(float(p))}")

    print("\nBy strategy:")
    cur.execute(f"SELECT strategy, COUNT(*), COUNT(*) FILTER (WHERE pnl>0), COALESCE(SUM(pnl),0) "
                f"FROM paper_trades WHERE {W} GROUP BY strategy ORDER BY 4 DESC", P)
    for strat, cnt, w, p in cur.fetchall():
        print(f"  {strat or '—':<12} {cnt:>4}   win {w/cnt*100:>4.0f}%   {_fmt(float(p))}")

    print("\nBy product:")
    cur.execute(f"SELECT product, COUNT(*), COALESCE(SUM(pnl),0) FROM paper_trades WHERE {W} "
                f"GROUP BY product ORDER BY 2 DESC", P)
    for prod, cnt, p in cur.fetchall():
        print(f"  {prod or '—':<12} {cnt:>4}   {_fmt(float(p))}")

    # daily P&L + running equity (best/worst day, simple drawdown)
    cur.execute(f"SELECT trade_date, COALESCE(SUM(pnl),0) FROM paper_trades WHERE {W} "
                f"GROUP BY trade_date ORDER BY trade_date", P)
    rows = cur.fetchall()
    daily = [(d, float(p)) for d, p in rows]
    best = max(daily, key=lambda x: x[1]); worst = min(daily, key=lambda x: x[1])
    equity, peak, maxdd = 0.0, 0.0, 0.0
    for _, p in daily:
        equity += p; peak = max(peak, equity); maxdd = min(maxdd, equity - peak)
    winning_days = sum(1 for _, p in daily if p > 0)
    print(f"\nDaily: {winning_days}/{len(daily)} green days   "
          f"best {_fmt(best[1]).strip()} ({best[0]})   worst {_fmt(worst[1]).strip()} ({worst[0]})")
    print(f"Max drawdown (close-of-day equity): {_fmt(maxdd)}")

    # signal decision coverage
    cur.execute(f"SELECT decision, COUNT(*) FROM paper_signal_decisions WHERE {W} GROUP BY decision", P)
    dec = dict(cur.fetchall())
    cur.execute(f"SELECT reason, COUNT(*) FROM paper_signal_decisions WHERE {W} AND decision='SKIPPED' "
                f"GROUP BY reason ORDER BY 2 DESC", P)
    skips = cur.fetchall()
    print(f"\nSignals seen: {sum(dec.values())}   executed {dec.get('EXECUTED',0)}   skipped {dec.get('SKIPPED',0)}")
    print("  skip reasons:", ", ".join(f"{r}={c}" for r, c in skips))
    print("=" * 68)
    conn.close()


if __name__ == "__main__":
    main()
