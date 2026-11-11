"""
strategies/backtest.py — backtest CLI for the pure strategies in this package.

    python -m strategies.backtest orb_cpr_nifty [--from 2022-01-01] [--to 2026-12-31]
                                                [--gates] [--no-grid] [--no-walkforward]

Reads `nifty_1m` (scripts/fetch_nifty_history.py), reuses the strategy's own
feature / evaluate / simulate functions, and reports:
  baseline (default Params, net of 3 pts) · cost sensitivity 0/3/6/10 pts ·
  by year · exit and skip reasons · parameter grid · rolling walk-forward
  (12 months in-sample, 3 months out-of-sample) · bootstrap 95% CI of mean R ·
  out-of-sample max drawdown.
Writes reports/<name>_trades.csv, reports/<name>_oos_trades.csv and
reports/<name>_report.md. `--gates` prints PASS/FAIL per go-live gate.

Walk-forward picks each window's parameters on in-sample average R (net of 3
pts) only; the full-sample grid is reported for robustness, never for selection.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
import time as _time
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / ".env")

from strategies import orb_cpr_nifty as S            # noqa: E402

REPORT_DIR = ROOT / "reports"
COSTS = (0.0, 3.0, 6.0, 10.0)
BASE_COST = 3.0
ROBUST_COST = 6.0
GRID = {                                              # 81 cells
    "or_min_atr": (0.15, 0.20, 0.25),
    "or_max_atr": (0.50, 0.60, 0.70),
    "target_r": (1.0, 1.5, 2.0),
    "cpr_max_pct": (0.4, 0.6, 0.8),
}
WF_IS_MONTHS = 12
WF_OOS_MONTHS = 3
WF_MIN_IS_TRADES = 20
GATE_MIN_OOS = 100
GATE_MIN_AVG_R = 0.10
GATE_MAX_DD_R = 12.0
GATE_GRID_POSITIVE = 0.60
RUPEES_PER_R = 2000.0
ACCOUNT_INR = 150_000.0


# ── Data ──────────────────────────────────────────────────────────────────────

def load_sessions(d0: date, d1: date, params: S.Params):
    import psycopg2
    conn = psycopg2.connect(os.environ["DB_URL"])
    df = pd.read_sql("SELECT ts, open, high, low, close, volume FROM nifty_1m "
                     "WHERE ts >= %s AND ts < %s + INTERVAL '1 day' ORDER BY ts",
                     conn, params=(d0, d1))
    conn.close()
    sessions = S.split_sessions(S.resample_5m(df, params), params)
    return df, sessions


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt(x: float, nd: int = 2) -> str:
    return "n/a" if x != x else f"{x:.{nd}f}"


def stats_line(label: str, trades: Sequence[S.Trade], cost: float) -> str:
    s = S.summarize(trades, cost)
    return (f"| {label} | {s['n']} | {fmt(s['avg_r'], 3)} | {fmt(s['win_rate'] * 100, 1)}% | "
            f"{fmt(s['total_r'], 1)} | {fmt(s['max_dd_r'], 1)} | {fmt(s['profit_factor'])} | "
            f"{fmt(s['avg_points'], 1)} |")


HEADER = "| set | n | avg R | win % | total R | max DD R | PF | avg pts |\n|---|---|---|---|---|---|---|---|"


def add_months(d: date, m: int) -> date:
    y, mo = d.year + (d.month - 1 + m) // 12, (d.month - 1 + m) % 12 + 1
    return date(y, mo, 1)


def grid_params(base: S.Params):
    keys = list(GRID)
    for combo in itertools.product(*(GRID[k] for k in keys)):
        yield replace(base, **dict(zip(keys, combo)))


def param_label(p: S.Params) -> str:
    return " ".join(f"{k}={getattr(p, k)}" for k in GRID)


# ── Analyses ──────────────────────────────────────────────────────────────────

def run_grid(sessions, feats, base: S.Params, days=None) -> List[Tuple[S.Params, dict]]:
    out = []
    for p in grid_params(base):
        trades, _ = S.run(sessions, feats, p, days)
        out.append((p, S.summarize(trades, BASE_COST)))
    return out


def walk_forward(sessions, feats, base: S.Params, log=print):
    """Rolling 12m IS / 3m OOS. Per window: grid on IS (avg R net 3 pts, needs
    WF_MIN_IS_TRADES trades, else the default Params), apply to OOS."""
    days = sorted(sessions)
    first = date(days[0].year, days[0].month, 1)
    last = days[-1]
    windows = []
    ws = first
    while add_months(ws, WF_IS_MONTHS) <= last:
        is0, is1 = ws, add_months(ws, WF_IS_MONTHS)
        oos1 = add_months(is1, WF_OOS_MONTHS)
        windows.append((is0, is1, oos1))
        ws = add_months(ws, WF_OOS_MONTHS)
    rows, oos_trades = [], []
    for is0, is1, oos1 in windows:
        is_days = [d for d in days if is0 <= d < is1]
        oos_days = [d for d in days if is1 <= d < oos1]
        if not oos_days:
            continue
        best_p, best = base, None
        for p in grid_params(base):
            tr, _ = S.run(sessions, feats, p, is_days)
            st = S.summarize(tr, BASE_COST)
            if st["n"] >= WF_MIN_IS_TRADES and (best is None or st["avg_r"] > best["avg_r"]):
                best_p, best = p, st
        if best is None:
            tr, _ = S.run(sessions, feats, base, is_days)
            best = S.summarize(tr, BASE_COST)
        oos_tr, _ = S.run(sessions, feats, best_p, oos_days)
        oos_trades.extend(oos_tr)
        oos_st = S.summarize(oos_tr, BASE_COST)
        rows.append({"is_from": is0, "is_to": is1, "oos_to": oos1, "params": param_label(best_p),
                     "is_n": best["n"], "is_avg_r": best["avg_r"],
                     "oos_n": oos_st["n"], "oos_avg_r": oos_st["avg_r"], "oos_total_r": oos_st["total_r"]})
        log(f"  WF {is0}..{is1} -> OOS to {oos1}: IS n={best['n']} avgR={fmt(best['avg_r'], 3)} | "
            f"OOS n={oos_st['n']} avgR={fmt(oos_st['avg_r'], 3)} | {param_label(best_p)}")
    oos_trades.sort(key=lambda t: t.entry_ts)
    return rows, oos_trades


def gates(oos_trades, grid_results, wf_rows) -> List[Tuple[str, Optional[bool], str]]:
    rs3 = S.r_series(oos_trades, BASE_COST)
    s3 = S.summarize(oos_trades, BASE_COST)
    s6 = S.summarize(oos_trades, ROBUST_COST)
    lo, hi = S.bootstrap_ci(rs3)
    pos = sum(1 for _, st in grid_results if st["n"] > 0 and st["avg_r"] > 0)
    share = pos / len(grid_results) if grid_results else 0.0
    distinct = len({r["params"] for r in wf_rows})
    dd_inr = s3["max_dd_r"] * RUPEES_PER_R
    g1 = s3["n"] >= GATE_MIN_OOS and s3["avg_r"] >= GATE_MIN_AVG_R and lo > 0
    g2 = (s6["n"] > 0 and s6["avg_r"] > 0) and share >= GATE_GRID_POSITIVE
    g3 = s3["max_dd_r"] <= GATE_MAX_DD_R
    return [
        ("1 walk-forward OOS net 3 pts: n>=100, avg R>=0.10, CI low>0", g1,
         f"n={s3['n']} avgR={fmt(s3['avg_r'], 3)} CI95=[{fmt(lo, 3)}, {fmt(hi, 3)}]"),
        ("2 robustness: avg R>0 at 6 pts; >=60% grid cells positive; stable params", g2,
         f"avgR@6pts={fmt(s6['avg_r'], 3)} grid positive={pos}/{len(grid_results)} ({share:.0%}) "
         f"distinct WF param sets={distinct}/{len(wf_rows)}"),
        ("3 OOS max drawdown <= 12R", g3,
         f"maxDD={fmt(s3['max_dd_r'], 1)}R = Rs {dd_inr:,.0f} = {dd_inr / ACCOUNT_INR:.1%} of Rs {ACCOUNT_INR:,.0f}"),
        ("4 paper phase: >=30 sessions with alerts + journal, realised vs backtest R within tolerance", None,
         "PENDING - paper phase not started"),
        ("5 live one lot only for >=20 sessions before any size change", None,
         "PENDING - after gate 4"),
    ]


# ── Report ────────────────────────────────────────────────────────────────────

def trades_frame(trades: Sequence[S.Trade]) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append({"trade_date": t.trade_date, "direction": t.direction, "signal_ts": t.signal_ts,
                     "entry_ts": t.entry_ts, "entry": t.entry, "stop_dist": t.stop_dist,
                     "exit_ts": t.exit_ts, "exit": t.exit, "reason": t.reason, "points": t.points,
                     "r_gross": t.r_gross, "r_net_3": t.r_net(3.0), "atr": t.atr,
                     "or_range": t.or_range, "cpr_width_pct": t.cpr_width_pct, "gap_pct": t.gap_pct})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", choices=["orb_cpr_nifty"])
    ap.add_argument("--from", dest="d0", default="2022-01-01")
    ap.add_argument("--to", dest="d1", default=date.today().isoformat())
    ap.add_argument("--gates", action="store_true")
    ap.add_argument("--no-grid", action="store_true")
    ap.add_argument("--no-walkforward", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):          # Windows console defaults to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)
    t0 = _time.time()
    base = S.Params()
    out: List[str] = []
    say = lambda s="": (print(s), out.append(s))   # noqa: E731

    df, sessions = load_sessions(d0, d1, base)
    feats = S.daily_features(sessions, base)
    days = sorted(sessions)
    say(f"# {args.name} backtest  {d0} -> {d1}  (generated {datetime.now():%Y-%m-%d %H:%M} IST)")
    say("")
    say(f"- 1-minute rows: {len(df):,}; valid sessions (>= {base.min_session_bars} five-minute bars): "
        f"{len(sessions)} ({days[0]} .. {days[-1]}); sessions with features: {len(feats)}")
    say(f"- params: {', '.join(f'{k}={v}' for k, v in asdict(base).items())}")
    say("")

    # baseline + cost sensitivity
    trades, skips = S.run(sessions, feats, base)
    say("## Baseline (default params) and cost sensitivity")
    say(HEADER)
    for c in COSTS:
        say(stats_line(f"cost {c:g} pts", trades, c))
    say("")
    say("Skips: " + ", ".join(f"{k}={v}" for k, v in sorted(skips.items())) +
        f"; signal days={len(trades)} of {len(sessions)}")
    say("")

    # by year
    say("## By year (net 3 pts)")
    say(HEADER)
    for y in sorted({t.trade_date.year for t in trades}):
        say(stats_line(str(y), [t for t in trades if t.trade_date.year == y], BASE_COST))
    say("")

    # exits
    say("## Exit reasons (net 3 pts)")
    say("| reason | n | avg R |\n|---|---|---|")
    for reason, n in Counter(t.reason for t in trades).most_common():
        rs = [t.r_net(BASE_COST) for t in trades if t.reason == reason]
        say(f"| {reason} | {n} | {fmt(sum(rs) / n, 3)} |")
    say("| LONG | %d | %s |" % (sum(1 for t in trades if t.direction == S.LONG),
                               fmt(S.summarize([t for t in trades if t.direction == S.LONG], BASE_COST)["avg_r"], 3)))
    say("| SHORT | %d | %s |" % (sum(1 for t in trades if t.direction == S.SHORT),
                                fmt(S.summarize([t for t in trades if t.direction == S.SHORT], BASE_COST)["avg_r"], 3)))
    say("")

    # grid
    grid_results: List[Tuple[S.Params, dict]] = []
    if not args.no_grid:
        say("## Parameter grid (full sample, net 3 pts; for robustness only, not selection)")
        grid_results = run_grid(sessions, feats, base)
        pos = sum(1 for _, st in grid_results if st["n"] > 0 and st["avg_r"] > 0)
        say(f"- cells: {len(grid_results)}; positive avg R: {pos} ({pos / len(grid_results):.0%}); "
            f"grid = {GRID}")
        say("| params | n | avg R | total R | max DD R |\n|---|---|---|---|---|")
        for p, st in sorted(grid_results, key=lambda x: -(x[1]['avg_r'] if x[1]['avg_r'] == x[1]['avg_r'] else -9))[:8]:
            say(f"| {param_label(p)} | {st['n']} | {fmt(st['avg_r'], 3)} | {fmt(st['total_r'], 1)} | {fmt(st['max_dd_r'], 1)} |")
        say("")

    # walk-forward
    wf_rows, oos_trades = [], []
    if not args.no_walkforward:
        say(f"## Walk-forward ({WF_IS_MONTHS}m in-sample / {WF_OOS_MONTHS}m out-of-sample, step {WF_OOS_MONTHS}m)")
        wf_rows, oos_trades = walk_forward(sessions, feats, base, log=lambda s: out.append(s) or print(s))
        say("")
        say("| IS from | IS to | OOS to | IS n | IS avg R | OOS n | OOS avg R | OOS total R | params |\n|---|---|---|---|---|---|---|---|---|")
        for r in wf_rows:
            say(f"| {r['is_from']} | {r['is_to']} | {r['oos_to']} | {r['is_n']} | {fmt(r['is_avg_r'], 3)} | "
                f"{r['oos_n']} | {fmt(r['oos_avg_r'], 3)} | {fmt(r['oos_total_r'], 1)} | {r['params']} |")
        say("")
        say("### Pooled out-of-sample")
        say(HEADER)
        for c in COSTS:
            say(stats_line(f"OOS cost {c:g} pts", oos_trades, c))
        lo, hi = S.bootstrap_ci(S.r_series(oos_trades, BASE_COST))
        say(f"- bootstrap 95% CI of mean R (net 3 pts): [{fmt(lo, 3)}, {fmt(hi, 3)}]")
        say(f"- distinct parameter sets chosen across windows: {len({r['params'] for r in wf_rows})} of {len(wf_rows)}")
        say("")

    # gates
    if args.gates:
        say("## Go-live gates")
        say("| gate | result | detail |\n|---|---|---|")
        for name, ok, detail in gates(oos_trades, grid_results, wf_rows):
            res = "PENDING" if ok is None else ("PASS" if ok else "FAIL")
            say(f"| {name} | **{res}** | {detail} |")
        say("")

    # files
    REPORT_DIR.mkdir(exist_ok=True)
    trades_frame(trades).to_csv(REPORT_DIR / f"{args.name}_trades.csv", index=False)
    trades_frame(oos_trades).to_csv(REPORT_DIR / f"{args.name}_oos_trades.csv", index=False)
    say(f"- wrote reports/{args.name}_trades.csv ({len(trades)} rows), "
        f"reports/{args.name}_oos_trades.csv ({len(oos_trades)} rows); elapsed {_time.time() - t0:.0f}s")
    (REPORT_DIR / f"{args.name}_report.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"report: reports/{args.name}_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
