#!/usr/bin/env python3
"""
scripts/backtest_newstrats.py — backtest CANDIDATE new strategies against the
incumbents, raw and regime-filtered, on the historical 5m candles.

Grounded in the 1-year finding (scripts/backtest_strategies.py): win rate is a
flat ~43% across all detectors, so edge = expectancy/selectivity, not hit rate.
The candidates therefore build on the three net-positive edges (VWAP_TREND, ORB,
VWAP_REV) and add conviction filters:

  VWAP_ORB        confluence — an opening-range breakout that is ALSO VWAP
                  trend-aligned, volume-confirmed and RSI on-side.
  VWAP_TREND_VOL  the best strategy (VWAP reclaim) + breakout-bar volume.
  VWAP_PULLBACK   trend-continuation — buy the pullback that dips to/through VWAP
                  and closes back above it inside an established VWAP uptrend.

Only promote a candidate into signals/detectors.py DETECTORS if its FILTERED
profit-factor beats VWAP_TREND-filtered (~1.09).

Usage:  python scripts/backtest_newstrats.py --months 12
"""
import argparse, os, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2
from signals.config import SignalConfig
from signals.detectors import (_mk, _finite, LONG, SHORT,
                               detect_orb, detect_vwap_trend, detect_vwap_reversal)
from signals.backtest import backtest_all, stats
from scripts.backtest_better import make_filtered, load_days, UNIVERSE

NEW_NAMES = ("VWAP_ORB", "VWAP_TREND_VOL", "VWAP_PULLBACK")


# ── candidate detectors ───────────────────────────────────────────────────────

def detect_vwap_orb(s):
    """Confluence: an opening-range breakout that is also VWAP trend-aligned,
    volume-confirmed and RSI on-side — the two best edges must agree."""
    cfg = s.cfg; i = s.n - 1; ob = cfg.orb_bars
    if i < ob:
        return None
    if s.trade_date is not None and \
            s.bars[0]["ts"] > datetime.combine(s.trade_date, cfg.session_start):
        return None                       # opening range must start at the open
    vwap = s.vwap(); rsi = s.rsi()
    if not (_finite(vwap[i]) and _finite(rsi[i])):
        return None
    avg = s.trailing_avg_volume(i)
    if avg is None or s.volume[i] < cfg.vol_mult * avg:
        return None
    orh = float(s.high[:ob].max()); orl = float(s.low[:ob].min()); c = float(s.close[i])
    direction = None
    if c > orh and c > vwap[i] and rsi[i] >= cfg.vwap_trend_rsi:
        direction = LONG
    elif c < orl and c < vwap[i] and rsi[i] <= (100.0 - cfg.vwap_trend_rsi):
        direction = SHORT
    return _mk(s, "VWAP_ORB", direction, i) if direction else None


def detect_vwap_trend_vol(s):
    """VWAP_TREND (best) + breakout-bar volume confirmation."""
    cfg = s.cfg; i = s.n - 1
    if i < 1:
        return None
    vwap = s.vwap(); rsi = s.rsi()
    if not all(_finite(x) for x in (vwap[i], vwap[i - 1], rsi[i])):
        return None
    avg = s.trailing_avg_volume(i)
    if avg is None or s.volume[i] < cfg.vol_mult * avg:
        return None
    c = s.close; direction = None
    if c[i] > vwap[i] and c[i - 1] <= vwap[i - 1] and rsi[i] >= cfg.vwap_trend_rsi:
        direction = LONG
    elif c[i] < vwap[i] and c[i - 1] >= vwap[i - 1] and rsi[i] <= (100.0 - cfg.vwap_trend_rsi):
        direction = SHORT
    return _mk(s, "VWAP_TREND_VOL", direction, i) if direction else None


def detect_vwap_pullback(s):
    """Trend continuation: inside an established VWAP uptrend, buy the pullback
    bar that dips to/through VWAP but closes back above it (mirror for shorts)."""
    cfg = s.cfg; i = s.n - 1
    if i < 3:
        return None
    vwap = s.vwap(); rsi = s.rsi()
    if not (_finite(vwap[i]) and _finite(vwap[i - 2]) and _finite(rsi[i])):
        return None
    c = s.close; lo = s.low; hi = s.high
    up = c[i - 1] > vwap[i - 1] and c[i - 2] > vwap[i - 2] and vwap[i] > vwap[i - 2]
    dn = c[i - 1] < vwap[i - 1] and c[i - 2] < vwap[i - 2] and vwap[i] < vwap[i - 2]
    direction = None
    if up and lo[i] <= vwap[i] and c[i] > vwap[i] and rsi[i] >= cfg.vwap_trend_rsi:
        direction = LONG
    elif dn and hi[i] >= vwap[i] and c[i] < vwap[i] and rsi[i] <= (100.0 - cfg.vwap_trend_rsi):
        direction = SHORT
    return _mk(s, "VWAP_PULLBACK", direction, i) if direction else None


CANDIDATES = [detect_vwap_orb, detect_vwap_trend_vol, detect_vwap_pullback]
INCUMBENTS = [detect_orb, detect_vwap_trend, detect_vwap_reversal]
ORDER = ["VWAP_ORB", "VWAP_TREND_VOL", "VWAP_PULLBACK", "VWAP_TREND", "ORB", "VWAP_REV"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--sl-atr", type=float, default=1.5)
    ap.add_argument("--tp-atr", type=float, default=2.0)
    args = ap.parse_args()

    cfg = SignalConfig()
    since = datetime.now() - timedelta(days=int(args.months * 30.5))
    raw = CANDIDATES + INCUMBENTS
    filt = [make_filtered(d) for d in raw]

    conn = psycopg2.connect(os.environ["DB_URL"]); cur = conn.cursor()
    agg_raw, agg_filt = defaultdict(list), defaultdict(list)
    print(f"New-strategy backtest - {len(UNIVERSE)} symbols - 5m - {args.months}mo "
          f"(SL={args.sl_atr} TP={args.tp_atr})")
    for sym in UNIVERSE:
        days = load_days(cur, sym, "5m", since)
        if not days:
            continue
        for strat, tr in backtest_all(sym, raw, days, cfg, args.sl_atr, args.tp_atr).items():
            agg_raw[strat].extend(tr)
        for strat, tr in backtest_all(sym, filt, days, cfg, args.sl_atr, args.tp_atr).items():
            agg_filt[strat].extend(tr)
    conn.close()

    def show(title, agg):
        print("\n" + "=" * 82)
        print(title)
        print(f"{'STRATEGY':<16}{'TRADES':>7}{'WIN%':>6}{'AVG%':>8}{'TOTAL%':>9}"
              f"{'PF':>6}{'MAXDD%':>8}{'SHARPE':>7}")
        print("-" * 82)
        for strat in ORDER:
            s = stats(agg.get(strat, []))
            if not s["trades"]:
                continue
            pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
            tag = "  <- NEW" if strat in NEW_NAMES else ""
            print(f"{strat:<16}{s['trades']:>7}{s['win_rate']:>6.1f}{s['avg_pnl']:>8.3f}"
                  f"{s['total_pnl']:>9.1f}{pf:>6}{s['max_dd']:>8.1f}{s['sharpe']:>7.1f}{tag}")

    show("RAW (no regime filter)", agg_raw)
    show("REGIME-FILTERED (trend-align + 09:45-14:00 + ATR% floor) - how they'd run live",
         agg_filt)
    print("\nPromote a NEW strategy only if its FILTERED profit-factor beats "
          "VWAP_TREND-filtered (~1.09). Costs still NOT modelled.")


if __name__ == "__main__":
    main()
