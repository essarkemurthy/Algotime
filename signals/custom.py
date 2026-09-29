"""User-defined strategies, evaluated alongside the built-in detectors.

A custom strategy is data, not code: a list of conditions comparing an indicator
against either a fixed level or another indicator, combined with all/any. The
engine turns each stored definition into a detector function with the same
`(SymbolSession) -> Optional[Signal]` shape as everything in DETECTORS, so a
custom strategy fires, dedups, notifies and reaches the paper algo exactly like
a built-in one.

Definitions live in data/custom_strategies.json and are reloaded when that file
changes, so edits from the UI take effect on the next bar without a restart.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from signals.detectors import Signal

log = logging.getLogger(__name__)

STORE = Path(__file__).resolve().parent.parent / "data" / "custom_strategies.json"

# Operators a condition may use. Equality on floats is deliberately a tolerance
# check — exact == on a computed indicator would essentially never be true.
_EPS = 1e-9

OPERATORS = (">", ">=", "<", "<=", "==", "!=", "cross_above", "cross_below")

# name -> (needs_period, needs_mult, human label)
INDICATORS: Dict[str, dict] = {
    "close":        {"args": [],                  "label": "Close"},
    "open":         {"args": [],                  "label": "Open"},
    "high":         {"args": [],                  "label": "High"},
    "low":          {"args": [],                  "label": "Low"},
    "volume":       {"args": [],                  "label": "Volume"},
    "vwap":         {"args": [],                  "label": "VWAP"},
    "atr":          {"args": [],                  "label": "ATR"},
    "rsi":          {"args": ["period"],          "label": "RSI"},
    "ema":          {"args": ["period"],          "label": "EMA"},
    "bb_upper":     {"args": ["period", "mult"],  "label": "Bollinger upper"},
    "bb_lower":     {"args": ["period", "mult"],  "label": "Bollinger lower"},
    "bb_mid":       {"args": ["period", "mult"],  "label": "Bollinger mid"},
    "supertrend":   {"args": ["period", "mult"],  "label": "Supertrend"},
    "donchian_high": {"args": ["period"],         "label": "Donchian high"},
    "donchian_low":  {"args": ["period"],         "label": "Donchian low"},
    "avg_volume":   {"args": [],                  "label": "Avg volume"},
}


def _series(sess, spec: dict):
    """Resolve an operand spec to a numeric series (list-like, indexable by -1/-2).

    Returns None when the indicator cannot be computed yet (too few bars), which
    makes the whole condition unevaluable rather than silently false.
    """
    kind = (spec or {}).get("kind", "value")
    if kind == "value":
        try:
            v = float(spec.get("value"))
        except (TypeError, ValueError):
            return None
        return [v, v]                      # constant series; prev == cur

    name = str(spec.get("name", "")).lower()
    period = int(spec.get("period") or 14)
    mult = float(spec.get("mult") or 2.0)

    try:
        if name == "close":   return sess.close
        if name == "open":    return sess._col("open")
        if name == "high":    return sess.high
        if name == "low":     return sess.low
        if name == "volume":  return sess.volume
        if name == "vwap":    return sess.vwap()
        if name == "atr":     return sess.atr()
        if name == "rsi":     return sess.rsi_n(period)
        if name == "ema":     return sess.ema(period)
        if name in ("bb_upper", "bb_lower", "bb_mid"):
            upper, mid, lower = sess.bollinger(period, mult)
            return {"bb_upper": upper, "bb_mid": mid, "bb_lower": lower}[name]
        if name == "supertrend":
            st = sess.supertrend(period, mult)
            return st[0] if isinstance(st, tuple) else st
        if name in ("donchian_high", "donchian_low"):
            hi, lo = sess.donchian(period)
            return hi if name == "donchian_high" else lo
        if name == "avg_volume":
            i = sess.n - 1
            av = sess.trailing_avg_volume(i)
            if av is None:
                return None
            prev = sess.trailing_avg_volume(i - 1)
            return [prev if prev is not None else av, av]
    except Exception as exc:
        log.debug("custom: indicator %s failed: %s", name, exc)
        return None
    return None


def _at(series, idx: int) -> Optional[float]:
    """series[-1] / series[-2] as a finite float, else None."""
    try:
        v = float(series[idx])
    except (IndexError, TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _compare(op: str, lhs_cur, lhs_prev, rhs_cur, rhs_prev) -> Optional[bool]:
    if op in ("cross_above", "cross_below"):
        if None in (lhs_cur, lhs_prev, rhs_cur, rhs_prev):
            return None
        if op == "cross_above":
            return lhs_prev <= rhs_prev and lhs_cur > rhs_cur
        return lhs_prev >= rhs_prev and lhs_cur < rhs_cur

    if lhs_cur is None or rhs_cur is None:
        return None
    if op == ">":  return lhs_cur > rhs_cur
    if op == ">=": return lhs_cur >= rhs_cur
    if op == "<":  return lhs_cur < rhs_cur
    if op == "<=": return lhs_cur <= rhs_cur
    if op == "==": return abs(lhs_cur - rhs_cur) <= _EPS
    if op == "!=": return abs(lhs_cur - rhs_cur) > _EPS
    return None


def evaluate(sess, defn: dict) -> Optional[bool]:
    """True/False if every condition could be evaluated, else None (not ready)."""
    conds = defn.get("conditions") or []
    if not conds:
        return None
    match = str(defn.get("match", "all")).lower()
    results: List[bool] = []
    for c in conds:
        ls = _series(sess, c.get("left"))
        rs = _series(sess, c.get("right"))
        if ls is None or rs is None:
            return None
        got = _compare(str(c.get("op", ">")),
                       _at(ls, -1), _at(ls, -2), _at(rs, -1), _at(rs, -2))
        if got is None:
            return None
        results.append(got)
    return any(results) if match == "any" else all(results)


def _describe(defn: dict) -> str:
    def side(spec):
        if (spec or {}).get("kind") == "value":
            return str(spec.get("value"))
        n = spec.get("name", "?")
        p = spec.get("period")
        return f"{n}({p})" if p and "period" in INDICATORS.get(n, {}).get("args", []) else n
    joiner = " OR " if str(defn.get("match", "all")).lower() == "any" else " AND "
    return joiner.join(f"{side(c.get('left'))} {c.get('op')} {side(c.get('right'))}"
                       for c in (defn.get("conditions") or []))


def make_detector(defn: dict) -> Callable:
    """Wrap a stored definition as a DETECTORS-compatible callable."""
    name = str(defn.get("id") or defn.get("name") or "CUSTOM").upper().replace(" ", "_")
    direction = str(defn.get("direction", "LONG")).upper()
    symbols = {s.upper() for s in (defn.get("symbols") or [])}

    def _detect(sess) -> Optional[Signal]:
        if symbols and sess.symbol.upper() not in symbols:
            return None
        if sess.n < 2:
            return None
        if evaluate(sess, defn) is not True:
            return None
        i = sess.n - 1
        close = _at(sess.close, -1)
        if close is None:
            return None
        vwap = _at(sess.vwap(), -1)
        rsi = _at(sess.rsi(), -1)
        atr = _at(sess.atr(), -1)
        av = sess.trailing_avg_volume(i)
        vol = _at(sess.volume, -1)
        return Signal(
            symbol=sess.symbol,
            strategy=name,
            direction=direction,
            ts=sess.bars[-1]["ts"],
            trade_date=sess.trade_date,
            trigger_price=close,
            vwap=vwap if vwap is not None else float("nan"),
            rsi=rsi if rsi is not None else float("nan"),
            vol_ratio=(vol / av) if (av and vol) else float("nan"),
            atr=atr if atr is not None else float("nan"),
        )

    _detect.__name__ = f"custom_{name.lower()}"
    _detect.strategy_name = name
    _detect.definition = defn
    return _detect


# ── store ────────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_cache: dict = {"mtime": None, "defs": [], "detectors": []}


def load_definitions() -> List[dict]:
    if not STORE.exists():
        return []
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("strategies", [])
    except Exception as exc:
        log.warning("custom strategies: could not read %s: %s", STORE, exc)
        return []


def save_definitions(defs: List[dict]) -> None:
    with _lock:
        STORE.parent.mkdir(exist_ok=True)
        STORE.write_text(json.dumps(defs, indent=2), encoding="utf-8")
        _cache["mtime"] = None          # force reload on next use


def active_detectors() -> List[Callable]:
    """Detectors for every enabled definition, rebuilt when the file changes."""
    try:
        mtime = STORE.stat().st_mtime if STORE.exists() else 0
    except OSError:
        mtime = 0
    with _lock:
        if _cache["mtime"] != mtime:
            defs = load_definitions()
            built = []
            for d in defs:
                if not d.get("enabled", True):
                    continue
                try:
                    built.append(make_detector(d))
                except Exception as exc:
                    log.warning("custom strategy %s is invalid: %s", d.get("id"), exc)
            _cache.update(mtime=mtime, defs=defs, detectors=built)
            if built:
                log.info("custom strategies: %d active (%s)", len(built),
                         ", ".join(getattr(b, "strategy_name", "?") for b in built))
        return list(_cache["detectors"])


def validate(defn: dict) -> List[str]:
    """Human-readable problems with a definition; empty list means it is usable."""
    errs: List[str] = []
    if not str(defn.get("name", "")).strip():
        errs.append("name is required")
    if str(defn.get("direction", "")).upper() not in ("LONG", "SHORT"):
        errs.append("direction must be LONG or SHORT")
    if str(defn.get("match", "all")).lower() not in ("all", "any"):
        errs.append("match must be all or any")
    conds = defn.get("conditions") or []
    if not conds:
        errs.append("at least one condition is required")
    for i, c in enumerate(conds, 1):
        if str(c.get("op")) not in OPERATORS:
            errs.append(f"condition {i}: operator must be one of {', '.join(OPERATORS)}")
        for sidename in ("left", "right"):
            spec = c.get(sidename) or {}
            kind = spec.get("kind", "value")
            if kind == "value":
                try:
                    float(spec.get("value"))
                except (TypeError, ValueError):
                    errs.append(f"condition {i}: {sidename} value must be a number")
            elif kind == "indicator":
                if str(spec.get("name", "")).lower() not in INDICATORS:
                    errs.append(f"condition {i}: unknown indicator "
                                f"'{spec.get('name')}'")
            else:
                errs.append(f"condition {i}: {sidename} kind must be value or indicator")
    return errs
