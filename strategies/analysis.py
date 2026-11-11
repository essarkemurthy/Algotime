"""
strategies/analysis.py — statistical checks used by the backtest reports.

No strategy logic here. Everything takes the trade lists / sessions the
strategy module produced and answers questions about them:

  slice_analysis   every slice examined, raw and Holm-adjusted p (multiplicity)
  like_for_like    fixed-spec baseline on exactly the OOS windows vs walk-forward OOS
  regime_check     rolling hit-rate range vs a stationary binomial of the same size
  funnel           day-filter funnel + data sanity checks that back the trade count
"""

from __future__ import annotations

import random
from collections import Counter, OrderedDict
from datetime import date, datetime, time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

from strategies import orb_cpr_nifty as S

ALPHA = 0.05


# ── multiplicity ──────────────────────────────────────────────────────────────

def holm(pvals: Sequence[float]) -> List[float]:
    """Holm step-down adjusted p-values (same order as the input)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


def welch_p(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided Welch t-test p for mean(a) != mean(b); 1.0 when a side is too small."""
    if len(a) < 5 or len(b) < 5:
        return 1.0
    return float(stats.ttest_ind(a, b, equal_var=False).pvalue)


def build_slices(trades: Sequence[S.Trade]) -> "OrderedDict[str, Dict[str, List[int]]]":
    """{dimension: {label: [trade indexes]}} for every slice we look at."""
    out: "OrderedDict[str, Dict[str, List[int]]]" = OrderedDict()

    def add(dim: str, key_fn):
        d: Dict[str, List[int]] = {}
        for i, t in enumerate(trades):
            d.setdefault(str(key_fn(t)), []).append(i)
        out[dim] = dict(sorted(d.items()))

    add("weekday", lambda t: t.trade_date.strftime("%a"))
    add("side", lambda t: t.direction)
    add("year", lambda t: t.trade_date.year)
    add("signal_hour", lambda t: t.signal_ts.hour)
    if trades:
        orx = np.array([t.or_range / t.atr for t in trades])
        cprx = np.array([t.cpr_width_pct for t in trades])
        q_or = np.quantile(orx, [1 / 3, 2 / 3])
        q_cpr = np.quantile(cprx, [1 / 3, 2 / 3])
        add("or_atr_tercile", lambda t: "T%d" % (1 + int(np.searchsorted(q_or, t.or_range / t.atr, side="right"))))
        add("cpr_width_tercile", lambda t: "T%d" % (1 + int(np.searchsorted(q_cpr, t.cpr_width_pct, side="right"))))
    add("gap_sign", lambda t: "gap_up" if t.gap_pct > 0 else "gap_down_or_flat")
    return out


def slice_analysis(trades: Sequence[S.Trade], cost: float) -> Tuple[List[dict], int]:
    """Rows: dim, label, n, mean_r, rest_mean_r, p_raw (slice vs complement,
    Welch), p_holm across ALL slices examined, flagged (p_holm < ALPHA)."""
    rs = np.array(S.r_series(trades, cost))
    slices = build_slices(trades)
    rows = []
    for dim, labels in slices.items():
        for label, idx in labels.items():
            mask = np.zeros(len(rs), dtype=bool)
            mask[idx] = True
            a, b = rs[mask], rs[~mask]
            rows.append({"dim": dim, "label": label, "n": int(mask.sum()),
                         "mean_r": float(a.mean()) if len(a) else float("nan"),
                         "rest_mean_r": float(b.mean()) if len(b) else float("nan"),
                         "p_raw": welch_p(a, b)})
    adj = holm([r["p_raw"] for r in rows])
    for r, pa in zip(rows, adj):
        r["p_holm"] = pa
        r["flagged"] = pa < ALPHA
    return rows, len(rows)


# ── like-for-like ─────────────────────────────────────────────────────────────

def bootstrap_mean_ci(x: Sequence[float], n_boot: int = 2000, seed: int = 7) -> Tuple[float, float]:
    return S.bootstrap_ci(list(x), n_boot=n_boot, seed=seed)


def bootstrap_diff_ci(a: Sequence[float], b: Sequence[float], n_boot: int = 2000,
                      seed: int = 11) -> Tuple[float, float]:
    """95% percentile CI of mean(a) - mean(b), independent resampling."""
    if not a or not b:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        ma = sum(rng.choice(a) for _ in range(len(a))) / len(a)
        mb = sum(rng.choice(b) for _ in range(len(b))) / len(b)
        diffs.append(ma - mb)
    diffs.sort()
    return diffs[int(0.025 * n_boot)], diffs[min(n_boot - 1, int(0.975 * n_boot))]


def like_for_like(sessions, feats, base: S.Params, wf_rows: Sequence[dict],
                  oos_trades: Sequence[S.Trade], cost: float) -> dict:
    """Fixed-spec params run on exactly the OOS date windows, vs the walk-forward OOS."""
    oos_days = []
    for r in wf_rows:
        oos_days += [d for d in sessions if r["is_to"] <= d < r["oos_to"]]
    oos_days = sorted(set(oos_days))
    base_trades, _ = S.run(sessions, feats, base, oos_days)
    rb = S.r_series(base_trades, cost)
    ro = S.r_series(oos_trades, cost)
    b_lo, b_hi = bootstrap_mean_ci(rb)
    o_lo, o_hi = bootstrap_mean_ci(ro)
    d_lo, d_hi = bootstrap_diff_ci(ro, rb)
    return {"days": len(oos_days), "from": oos_days[0] if oos_days else None,
            "to": oos_days[-1] if oos_days else None,
            "base": S.summarize(base_trades, cost), "base_ci": (b_lo, b_hi),
            "oos": S.summarize(oos_trades, cost), "oos_ci": (o_lo, o_hi),
            "diff": (float(np.mean(ro)) - float(np.mean(rb))) if rb and ro else float("nan"),
            "diff_ci": (d_lo, d_hi),
            "selection_added": bool(rb and ro and d_lo > 0)}


# ── regime check ──────────────────────────────────────────────────────────────

def rolling_hit_range(hits: Sequence[int], window: int) -> Tuple[float, float]:
    x = np.asarray(hits, dtype=float)
    if len(x) < window:
        return float("nan"), float("nan")
    c = np.convolve(x, np.ones(window), "valid") / window
    return float(c.min()), float(c.max())


def regime_check(trades: Sequence[S.Trade], cost: float, window: int = 50,
                 n_sim: int = 2000, seed: int = 5) -> dict:
    """Observed rolling-`window` hit-rate range vs the 95% band of a stationary
    binomial with the same hit rate, length and number of overlapping windows."""
    rs = S.r_series(trades, cost)
    hits = [1 if r > 0 else 0 for r in rs]
    n = len(hits)
    p = sum(hits) / n if n else float("nan")
    obs_min, obs_max = rolling_hit_range(hits, window)
    rng = np.random.default_rng(seed)
    mins, maxs = [], []
    for _ in range(n_sim):
        sim = rng.random(n) < p
        lo, hi = rolling_hit_range(sim.astype(int), window)
        mins.append(lo); maxs.append(hi)
    band_min = (float(np.quantile(mins, 0.025)), float(np.quantile(mins, 0.975)))
    band_max = (float(np.quantile(maxs, 0.025)), float(np.quantile(maxs, 0.975)))
    outside = (obs_min < band_min[0]) or (obs_max > band_max[1])
    return {"n": n, "p": p, "window": window, "windows": max(0, n - window + 1),
            "obs_min": obs_min, "obs_max": obs_max, "band_min": band_min, "band_max": band_max,
            "outside": outside}


# ── funnel + sanity ───────────────────────────────────────────────────────────

FUNNEL_ORDER = ("gap", "or_min", "or_max", "cpr", "or_break", "cpr_align")


def day_flags(bars: Sequence[S.Bar], f: S.DayFeatures, p: S.Params) -> Dict[str, bool]:
    """Independent (non-sequential) filter outcomes for one session, recomputed
    from the bars so the funnel can be shown in any order."""
    or_bars = [b for b in bars if b.ts.time() < p.or_end]
    if not or_bars:
        return {k: False for k in FUNNEL_ORDER}
    orh, orl = max(b.high for b in or_bars), min(b.low for b in or_bars)
    rng = orh - orl
    win = [b for b in bars if p.signal_start < b.close_time(p.bar_minutes) <= p.signal_end
           and b.ts.time() >= p.or_end]
    return {
        "gap": abs(bars[0].open - f.prev_close) <= p.gap_atr_max * f.atr,
        "or_min": rng >= p.or_min_atr * f.atr,
        "or_max": rng <= p.or_max_atr * f.atr,
        "cpr": f.cpr_width_pct <= p.cpr_max_pct,
        "or_break": any(b.close > orh or b.close < orl for b in win),
        "cpr_align": any((b.close > orh and b.close > f.cpr_top) or
                         (b.close < orl and b.close < f.cpr_bottom) for b in win),
    }


def funnel(df_1m, sessions: Dict[date, List[S.Bar]], feats: Dict[date, S.DayFeatures],
           params: S.Params, trades: Sequence[S.Trade]) -> dict:
    """Session funnel from raw 1-minute data down to trades, plus sanity checks."""
    import pandas as pd
    ts = pd.to_datetime(df_1m["ts"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    dup = int(ts.duplicated().sum())
    per_day = ts.groupby(ts.dt.date).agg(["count", "min"])
    raw_days = list(per_day.index)
    weekend = [d for d in raw_days if d.weekday() >= 5]
    five_min = (per_day["count"] // params.bar_minutes)
    short = [d for d in raw_days if d.weekday() < 5 and five_min[d] < params.min_session_bars]
    valid = sorted(sessions)
    not_915 = [d for d in valid if sessions[d][0].ts.time() != params.session_open]
    with_feats = [d for d in valid if d in feats]

    counts = OrderedDict()
    counts["sessions in 1m data"] = len(raw_days)
    counts["- weekend special sessions"] = len(weekend)
    counts["- fewer than %d five-minute bars" % params.min_session_bars] = len(short)
    counts["= valid sessions"] = len(valid)
    counts["- no features (first %d sessions)" % (params.atr_period + 1)] = len(valid) - len(with_feats)
    counts["= evaluable sessions"] = len(with_feats)
    alive = list(with_feats)
    flags = {d: day_flags(sessions[d], feats[d], params) for d in alive}
    for k in FUNNEL_ORDER:
        alive = [d for d in alive if flags[d][k]]
        counts["pass %s" % k] = len(alive)
    by_year = Counter(t.trade_date.year for t in trades)
    return {"counts": counts, "duplicates_1m": dup, "weekend": weekend, "short": short,
            "not_0915": not_915, "survivors": len(alive), "trades": len(trades),
            "trades_by_year": dict(sorted(by_year.items())),
            "survivors_equal_trades": len(alive) == len(trades)}
