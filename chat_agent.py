"""
chat_agent.py — "ask the desk" analyst chatbot over the app's live state.

Pure functions plus one thin Claude call, so everything except the network is
unit-testable. `app.py` collects the raw state (`/api/status`, paper engine,
algo engine, live bridge, LTP cache, today's journal, stored NIFTY bars, the live
option chain) and hands it to `build_snapshot()`; the trimmed snapshot rides inside
the LAST user message only, so the (cached) system prompt and the earlier turns
stay byte-stable.

The bot analyses and explains — trend, levels, a CE/PE plan with entry, stop and
target — the way a desk analyst would when asked. It never places, exits, arms or
toggles anything; real orders stay behind the two gates in live_orders.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover
    _IST = None

DEFAULT_MODEL = "claude-opus-5-5"
MODEL = os.environ.get("CHAT_MODEL", DEFAULT_MODEL)
EFFORT = os.environ.get("CHAT_EFFORT", "medium")
MAX_TOKENS = 3000
MAX_HISTORY_TURNS = 20          # user+assistant messages kept from the browser
MAX_TURN_CHARS = 4000
MAX_QUESTION_CHARS = 2000
MAX_SIGNALS = 12
MAX_TRADES_TODAY = 30
INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
                 "NIFTYNEXT50", "CNXIT", "INDIAVIX")

# market context sizes
DAILY_ROWS_KEPT = 10            # recent sessions listed in full
INTRADAY_BARS_KEPT = 12         # most recent 5-minute bars listed in full
CHAIN_STRIKES_EACH_SIDE = 4
VIX_MAX_AGE_DAYS = 3

SYSTEM_PROMPT = """You are the desk analyst inside Algotime, a personal Indian index-options trading dashboard
(ICICI Breeze feed, NSE, times in IST). The operator trades NIFTY weekly options (CE = call, PE = put)
and asks you for the same kind of analysis they would get from Claude in a chat window: what the trend
is, where the levels are, whether this is a moment to take a position, and a concrete CE/PE plan with
entry, stop and target. Give it. A JSON snapshot of the app's state and the NIFTY market context at the
moment of the question is attached inside <situation> tags in their message.

How to analyse
- Work from the snapshot: daily bars, ATR, moving averages, daily and 5-minute RSI/ADX, the previous
  session's pivot/CPR/Camarilla levels, today's open, gap, opening range, high/low, the latest 5-minute
  bars, the option chain (ATM, PCR, strikes with the largest CE and PE open interest), VIX and the time
  of day. Say which of these drive your view.
- State the trend on two horizons (daily and intraday) and the day type as you read it (trend day,
  range day, gap-and-go, gap-fill, undecided). When the evidence is mixed, say so and say what would
  resolve it (for example "a 5-minute close above R1 at 25,900").
- When asked for a position or for CE/PE levels, give a plan: side (CE or PE, or no trade and why),
  the index condition that triggers the entry, the strike (ATM or one step in the money, named with
  the chain's expiry), the index level that invalidates it (stop), the first and second targets
  (nearest levels), the suggested time window and the time by which to be flat (the engine squares
  off at 15:15; nothing should be carried past 15:20). Quote the option premium from the chain when it
  is there, and the index levels that map to the plan. If the chain is absent, give index levels and
  say the premium is not available.
- Size in lots, risking at most 0.5-1% of the paper capital on the index-level stop, and say the
  rupee risk. Remind that weekly premiums on expiry day lose value fast.
- Be honest about uncertainty. This is analysis for the operator to judge, not a guarantee: say so in
  one short line at the end (once per answer, not in every sentence). Never call any setup reliable
  or describe past paper strategies as profitable; the app's own paper record is net negative and the
  pre-registered backtests of opening-range and pivot-level systems on NIFTY failed. You may use those
  level families as a map, but say that the mechanical versions did not beat costs.
- Quote the numbers you rely on: index levels with no decimals, premiums with two decimals, rupees
  with the ₹ sign and whole rupees for P&L. Name the strategy, instrument and side when you talk about
  a position. If something is not in the snapshot, say it is not available rather than inventing it.

Keep these distinctions sharp
- "paper" positions are simulated (paper_manual = hand-placed on the paper page, paper_algo = the
  strategy engine). Real money moves only through the live order bridge; say whether it is armed, in
  dry-run, or disarmed before calling anything "live".
- unrealised P&L (open positions, marked at the last traded price) versus realised P&L (closed).
- the intraday "mean_price_no_volume" is a running average of the index price, not a true VWAP; the
  index feed has no volume.

You cannot place, exit, arm or toggle anything; if asked to act, say so and point to the control on
the page. Format: lead with the direct answer, then the reasoning and the plan as a short list, with
plain prose otherwise. No preamble, no headings."""


# ── snapshot ──────────────────────────────────────────────────────────────────

def _r(x: Any, nd: int = 2) -> Any:
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return x


def _trim_algo(snap: Optional[dict]) -> Optional[dict]:
    if not snap:
        return None
    per = snap.get("strategies") or []
    per_list = list(per.values()) if isinstance(per, dict) else list(per)
    signals = snap.get("signals_log") or []
    keep_sig = ("ts", "time", "strategy", "symbol", "direction", "status", "decision", "reason",
                "price", "product")
    sig_out = []
    for s in list(signals)[:MAX_SIGNALS]:
        if isinstance(s, dict):
            sig_out.append({k: s[k] for k in keep_sig if k in s})
    return {
        "enabled_strategies": [p.get("strategy") for p in per_list if p.get("enabled")],
        "config": snap.get("config"),
        "open_count": snap.get("open_count"),
        "open_positions": snap.get("open_positions") or [],
        "realised_today": snap.get("realised_pnl"),
        "outcomes_today": snap.get("outcomes"),
        "per_strategy_today": [p for p in per_list
                               if p.get("open") or p.get("closed") or p.get("enabled")],
        "recent_signals": sig_out,
    }


def _trim_live(state: Optional[dict]) -> Optional[dict]:
    if not state:
        return None
    keep = ("env_enabled", "armed", "dry_run", "active", "killed", "disarm_reason", "armed_at",
            "lots", "max_lots", "max_open", "capital", "capital_at_arm", "risk_budget",
            "daily_loss_cap_inr", "realised_today", "trades_today", "consec_losses", "last_sizing",
            "funds_error", "open", "open_positions", "positions")
    out = {k: state[k] for k in keep if k in state}
    if not out:
        out = dict(state)
    return out


def _trim_trades(rows: Optional[Iterable[dict]], limit: int) -> List[dict]:
    keep = ("closed_ts", "source", "strategy", "product", "instrument", "symbol", "direction",
            "qty", "entry", "exit", "pnl", "reason")
    out = []
    for r in list(rows or [])[:limit]:
        if isinstance(r, dict):
            d = {k: r[k] for k in keep if k in r}
            for k in ("closed_ts",):
                if hasattr(d.get(k), "isoformat"):
                    d[k] = d[k].isoformat(timespec="seconds")
            out.append(d)
    return out


def alltime_totals(rows: Optional[Iterable[dict]]) -> dict:
    """Realised P&L by product over a list of closed paper trades."""
    tot: Dict[str, dict] = {}
    for r in rows or []:
        prod = str(r.get("product") or "unknown")
        d = tot.setdefault(prod, {"trades": 0, "wins": 0, "pnl": 0.0})
        pnl = float(r.get("pnl") or 0.0)
        d["trades"] += 1
        d["wins"] += 1 if pnl > 0 else 0
        d["pnl"] += pnl
    grand = {"trades": sum(d["trades"] for d in tot.values()),
             "pnl": round(sum(d["pnl"] for d in tot.values()), 2)}
    for d in tot.values():
        d["pnl"] = round(d["pnl"], 2)
        d["win_rate_pct"] = round(100.0 * d["wins"] / d["trades"], 1) if d["trades"] else None
    return {"by_product": tot, "total": grand}


# ── market context (NIFTY) ────────────────────────────────────────────────────

def _naive(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is not None:
        if _IST is not None:
            ts = ts.astimezone(_IST)
        ts = ts.replace(tzinfo=None)
    return ts


def _bars(rows: Optional[Iterable[dict]]) -> List[dict]:
    out = []
    for r in rows or []:
        ts = _naive(r.get("ts"))
        if ts is None:
            continue
        try:
            out.append({"ts": ts, "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"])})
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda b: b["ts"])
    return out


def _last(values: Sequence[Optional[float]], back: int = 0) -> Optional[float]:
    if len(values) <= back:
        return None
    v = values[-1 - back]
    return _r(v) if v is not None else None


def _sma(closes: Sequence[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return _r(sum(closes[-n:]) / n)


def _indicators(highs, lows, closes, period: int = 14) -> dict:
    """ATR/RSI/ADX series via strategies.common; empty dict when it cannot import."""
    try:
        from strategies.common import adx_wilder, atr_wilder, rsi_wilder
    except Exception:  # pragma: no cover
        return {}
    return {"atr": atr_wilder(highs, lows, closes, period),
            "rsi": rsi_wilder(closes, period),
            "adx": adx_wilder(highs, lows, closes, period)}


def _pivots(h: float, l: float, c: float) -> Dict[str, float]:
    try:
        from strategies.pcl_nifty import pivot_levels
        lv = pivot_levels(h, l, c)
    except Exception:  # pragma: no cover
        p = (h + l + c) / 3.0
        bc = (h + l) / 2.0
        tc = 2.0 * p - bc
        rng = h - l
        lv = {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "BC": bc, "TC": tc,
              "CPR_TOP": max(bc, tc), "CPR_BOTTOM": min(bc, tc),
              "H3": c + 1.1 * rng / 4, "H4": c + 1.1 * rng / 2,
              "L3": c - 1.1 * rng / 4, "L4": c - 1.1 * rng / 2}
    lv["R2"] = lv["P"] + (h - l)
    lv["S2"] = lv["P"] - (h - l)
    return {k: _r(v) for k, v in lv.items()}


def _nearest_levels(price: float, levels: Dict[str, float]) -> dict:
    above = [(v, k) for k, v in levels.items() if v > price]
    below = [(v, k) for k, v in levels.items() if v <= price]
    out = {}
    if above:
        v, k = min(above)
        out["above"] = {"name": k, "level": v, "distance": _r(v - price)}
    if below:
        v, k = max(below)
        out["below"] = {"name": k, "level": v, "distance": _r(price - v)}
    return out


def _trim_chain(chain: Optional[dict]) -> Optional[dict]:
    if not chain or not chain.get("rows"):
        return None
    rows = [r for r in chain["rows"] if isinstance(r, dict) and r.get("strike")]
    atm = chain.get("atm")
    if atm is None and rows:
        atm = rows[len(rows) // 2]["strike"]
    rows.sort(key=lambda r: r["strike"])
    idx = min(range(len(rows)), key=lambda i: abs(rows[i]["strike"] - atm)) if rows else 0
    lo, hi = max(0, idx - CHAIN_STRIKES_EACH_SIDE), min(len(rows), idx + CHAIN_STRIKES_EACH_SIDE + 1)

    def side(d):
        if not d:
            return None
        return {"ltp": _r(d.get("ltp")), "oi": d.get("oi"), "iv": _r(d.get("iv"), 1)}

    near = [{"strike": r["strike"], "ce": side(r.get("ce")), "pe": side(r.get("pe"))}
            for r in rows[lo:hi]]
    ce_max = max((r for r in rows if r.get("ce")), key=lambda r: r["ce"].get("oi") or 0, default=None)
    pe_max = max((r for r in rows if r.get("pe")), key=lambda r: r["pe"].get("oi") or 0, default=None)
    return {
        "expiry": chain.get("expiry"),
        "spot": _r(chain.get("spot")),
        "atm": atm,
        "pcr": chain.get("pcr"),
        "max_ce_oi_strike": ce_max["strike"] if ce_max else None,
        "max_pe_oi_strike": pe_max["strike"] if pe_max else None,
        "strikes_near_atm": near,
        "lot_size": chain.get("lot_size"),
        "note": "CE/PE ltp = option premium per unit; max OI strikes are where writers sit "
                "(CE wall above = resistance, PE wall below = support).",
    }


def market_context(*, daily: Optional[Iterable[dict]] = None,
                   intraday: Optional[Iterable[dict]] = None, bar_minutes: int = 5,
                   chain: Optional[dict] = None, vix: Optional[dict] = None,
                   ltp: Optional[float] = None, now: Optional[datetime] = None) -> dict:
    """NIFTY context for analysis: daily trend measures, previous-session levels,
    today's structure, recent bars, option chain, VIX. All derived from stored
    bars, so it is testable with synthetic rows."""
    now = now or (datetime.now(_IST) if _IST else datetime.now())
    now_n = now.replace(tzinfo=None)
    out: dict = {"symbol": "NIFTY", "bar_minutes": bar_minutes}

    d_bars = _bars(daily)
    # the stored daily row for today (if any) is partial; derive today from intraday instead
    d_bars = [b for b in d_bars if b["ts"].date() < now_n.date()]
    if d_bars:
        highs = [b["high"] for b in d_bars]
        lows = [b["low"] for b in d_bars]
        closes = [b["close"] for b in d_bars]
        ind = _indicators(highs, lows, closes)
        recent = []
        prev_c = None
        for b in d_bars[-DAILY_ROWS_KEPT:]:
            row = {"date": b["ts"].date().isoformat(), "o": _r(b["open"]), "h": _r(b["high"]),
                   "l": _r(b["low"]), "c": _r(b["close"])}
            if prev_c:
                row["chg_pct"] = _r(100.0 * (b["close"] - prev_c) / prev_c)
            prev_c = b["close"]
            recent.append(row)
        # the first listed row needs the close before it for its change
        k = len(d_bars) - DAILY_ROWS_KEPT - 1
        if k >= 0 and recent:
            recent[0]["chg_pct"] = _r(100.0 * (d_bars[k + 1]["close"] - d_bars[k]["close"])
                                      / d_bars[k]["close"])
        last = d_bars[-1]
        wk = d_bars[-5:]
        out["daily"] = {
            "sessions_loaded": len(d_bars),
            "prev_session": {"date": last["ts"].date().isoformat(), "o": _r(last["open"]),
                             "h": _r(last["high"]), "l": _r(last["low"]), "c": _r(last["close"])},
            "recent_sessions": recent,
            "atr14": _last(ind.get("atr", [])),
            "rsi14": _last(ind.get("rsi", [])),
            "adx14": _last(ind.get("adx", [])),
            "adx14_5_sessions_ago": _last(ind.get("adx", []), 5),
            "sma20": _sma(closes, 20),
            "sma50": _sma(closes, 50),
            "chg_5_sessions_pct": _r(100.0 * (closes[-1] - closes[-6]) / closes[-6]) if len(closes) > 5 else None,
            "chg_20_sessions_pct": _r(100.0 * (closes[-1] - closes[-21]) / closes[-21]) if len(closes) > 20 else None,
            "week_high": _r(max(b["high"] for b in wk)),
            "week_low": _r(min(b["low"] for b in wk)),
        }
        lv = _pivots(last["high"], last["low"], last["close"])
        cpr_w = lv["CPR_TOP"] - lv["CPR_BOTTOM"]
        out["levels_from_prev_session"] = {
            **lv,
            "cpr_width_pct_of_close": _r(100.0 * cpr_w / last["close"], 3),
            "prev_high": _r(last["high"]), "prev_low": _r(last["low"]), "prev_close": _r(last["close"]),
            "note": "P/R1/R2/S1/S2 classic pivots; CPR = central pivot range (TC/BC); "
                    "H3/H4/L3/L4 Camarilla. Backtested mechanically on NIFTY: no edge net of costs.",
        }

    i_bars = _bars(intraday)
    today = [b for b in i_bars if b["ts"].date() == now_n.date()]
    if i_bars:
        highs = [b["high"] for b in i_bars]
        lows = [b["low"] for b in i_bars]
        closes = [b["close"] for b in i_bars]
        ind = _indicators(highs, lows, closes)
        half_hour = max(1, 30 // bar_minutes)
        intr = {
            "bars_loaded": len(i_bars),
            "last_bar_open_time": i_bars[-1]["ts"].strftime("%H:%M"),
            "rsi14": _last(ind.get("rsi", [])),
            "rsi14_30min_ago": _last(ind.get("rsi", []), half_hour),
            "adx14": _last(ind.get("adx", [])),
            "adx14_30min_ago": _last(ind.get("adx", []), half_hour),
            "atr14_bars": _last(ind.get("atr", [])),
            "last_bars": [{"t": b["ts"].strftime("%H:%M"), "o": _r(b["open"]), "h": _r(b["high"]),
                           "l": _r(b["low"]), "c": _r(b["close"])}
                          for b in i_bars[-INTRADAY_BARS_KEPT:]],
        }
        if today:
            or_end = time(9, 30)
            orb = [b for b in today if b["ts"].time() < or_end]
            day_open = today[0]["open"]
            tp = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in today]
            intr.update({
                "today_open": _r(day_open),
                "today_high": _r(max(b["high"] for b in today)),
                "today_low": _r(min(b["low"] for b in today)),
                "last_close": _r(today[-1]["close"]),
                "opening_range_0915_0930": {"high": _r(max(b["high"] for b in orb)),
                                            "low": _r(min(b["low"] for b in orb))} if orb else None,
                "mean_price_no_volume": _r(sum(tp) / len(tp)),
                "bars_today": len(today),
            })
            pc = (out.get("daily") or {}).get("prev_session", {}).get("c")
            if pc:
                intr["gap_pct"] = _r(100.0 * (day_open - pc) / pc)
                intr["gap_points"] = _r(day_open - pc)
                intr["chg_from_prev_close_pct"] = _r(100.0 * (today[-1]["close"] - pc) / pc)
            atr = (out.get("daily") or {}).get("atr14")
            if atr:
                intr["today_range_in_atr"] = _r((max(b["high"] for b in today)
                                                 - min(b["low"] for b in today)) / atr)
        out["intraday"] = intr

    ref = ltp if ltp is not None else (today[-1]["close"] if today else None)
    if ref is not None and out.get("levels_from_prev_session"):
        lv = {k: v for k, v in out["levels_from_prev_session"].items()
              if isinstance(v, (int, float)) and k not in ("cpr_width_pct_of_close",)}
        if out.get("intraday"):
            for k in ("today_high", "today_low"):
                if out["intraday"].get(k) is not None:
                    lv[k] = out["intraday"][k]
            o = out["intraday"].get("opening_range_0915_0930") or {}
            if o:
                lv["OR_high"], lv["OR_low"] = o["high"], o["low"]
        out["reference_price"] = _r(ref)
        out["nearest_levels"] = _nearest_levels(float(ref), lv)

    ch = _trim_chain(chain)
    if ch:
        out["option_chain"] = ch

    if vix and vix.get("value") is not None:
        ts = _naive(vix.get("ts"))
        if ts is None or (now_n - ts) <= timedelta(days=VIX_MAX_AGE_DAYS):
            out["india_vix"] = {"value": _r(vix["value"]),
                                "as_of": ts.isoformat(timespec="minutes") if ts else None}

    out["session_clock"] = {
        "now": now_n.strftime("%H:%M"),
        "minutes_to_1515_squareoff": int((datetime.combine(now_n.date(), time(15, 15)) - now_n)
                                         .total_seconds() // 60),
        "is_expiry_day": _is_expiry_day(now_n.date(), (ch or {}).get("expiry")),
    }
    return out


def _is_expiry_day(d, expiry: Any) -> Optional[bool]:
    if not expiry:
        return None
    try:
        return str(expiry)[:10] == d.isoformat()
    except Exception:
        return None


def build_snapshot(*, status: Optional[dict] = None, funds: Optional[dict] = None,
                   ltp: Optional[Dict[str, float]] = None, prev_close: Optional[Dict[str, float]] = None,
                   algo: Optional[dict] = None, paper_summary: Optional[dict] = None,
                   manual_positions: Optional[dict] = None, live: Optional[dict] = None,
                   trades_today: Optional[Sequence[dict]] = None,
                   alltime: Optional[dict] = None, market: Optional[dict] = None,
                   now: Optional[datetime] = None) -> dict:
    """Trim the app's raw state to what a question about 'the position' or
    'the market' needs."""
    now = now or (datetime.now(_IST) if _IST else datetime.now())
    ltp = ltp or {}
    indices = {}
    for sym in INDEX_SYMBOLS:
        if sym in ltp:
            entry = {"ltp": _r(ltp[sym])}
            pc = (prev_close or {}).get(sym)
            if pc:
                entry["prev_close"] = _r(pc)
                entry["change_pct"] = _r(100.0 * (float(ltp[sym]) - float(pc)) / float(pc))
            indices[sym] = entry
    # LTPs of whatever is open, so the bot can mark positions without asking.
    held = set()
    for src in ((algo or {}).get("open_positions") or [],
                (paper_summary or {}).get("open_positions") or [],
                (manual_positions or {}).get("positions") or []):
        for p in src:
            if isinstance(p, dict) and p.get("symbol"):
                held.add(p["symbol"])
    held_ltp = {s: _r(ltp[s]) for s in sorted(held) if s in ltp}

    ps = dict(paper_summary or {})
    paper = {k: ps.get(k) for k in ("starting_capital", "cash", "invested", "unrealised_pnl",
                                    "realised_pnl", "total_pnl", "pnl_pct", "equity")
             if k in ps}
    paper["open_positions"] = ps.get("open_positions") or []

    cs = (status or {}).get("candle_sync") or {}
    return {
        "as_of": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "market_session": "open" if (now.weekday() < 5 and "09:15:00" <= now.strftime("%H:%M:%S")
                                     < "15:30:00") else "closed",
        "feed": {"broker_connected": (status or {}).get("connected"),
                 "algo_loop_running": (status or {}).get("algo_running"),
                 "candles_last_sync": cs.get("last_run"), "candles_last_result": cs.get("last_result")},
        "indices": indices,
        "nifty_market": market,
        "held_symbol_ltp": held_ltp,
        "broker_funds": funds,
        "paper_manual": paper,
        "paper_algo": _trim_algo(algo),
        "paper_manual_options_legacy": manual_positions,
        "live_bridge": _trim_live(live),
        "closed_today": _trim_trades(trades_today, MAX_TRADES_TODAY),
        "alltime_paper_record": alltime,
    }


# ── messages ──────────────────────────────────────────────────────────────────

def _clean_history(history: Optional[Iterable[dict]]) -> List[dict]:
    """Browser-held turns -> alternating user/assistant text messages."""
    out: List[dict] = []
    for m in list(history or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        text = str(m.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        text = text[:MAX_TURN_CHARS]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":      # the new question follows; avoid two user turns
        out.pop()
    return out


def build_messages(history: Optional[Iterable[dict]], question: str, snapshot: dict) -> List[dict]:
    q = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not q:
        raise ValueError("empty question")
    body = json.dumps(snapshot, default=str, ensure_ascii=False, separators=(",", ":"))
    return _clean_history(history) + [{
        "role": "user",
        "content": f"{q}\n\n<situation>\n{body}\n</situation>",
    }]


# ── Claude call ───────────────────────────────────────────────────────────────

def api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def make_client():
    """anthropic.Anthropic() or None when no credential is configured."""
    if not api_key_present():
        return None
    import anthropic
    return anthropic.Anthropic(max_retries=2, timeout=120.0)


def _text_of(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def ask(client, history: Optional[Iterable[dict]], question: str, snapshot: dict,
        model: str = MODEL) -> dict:
    """One answer. Raises anthropic errors to the caller (app maps them to HTTP)."""
    messages = build_messages(history, question, snapshot)
    kwargs = dict(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": EFFORT},
    )
    try:
        # Server-side refusal fallback (routes a declined request to another model).
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"}, **kwargs)
    except Exception as exc:  # the beta may be unavailable on this account/SDK: retry plain
        msg = str(exc).lower()
        if "fallback" not in msg and "beta" not in msg:
            raise
        response = client.beta.messages.create(**kwargs)

    stop = getattr(response, "stop_reason", None)
    text = _text_of(response)
    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        why = getattr(details, "explanation", None) if details else None
        text = text or ("I can't answer that one." + (f" ({why})" if why else ""))
    elif stop == "max_tokens":
        text += "\n\n[answer cut at the token limit]"
    usage = getattr(response, "usage", None)
    return {
        "answer": text,
        "model": getattr(response, "model", model),
        "stop_reason": stop,
        "usage": {"input": getattr(usage, "input_tokens", None),
                  "output": getattr(usage, "output_tokens", None),
                  "cache_read": getattr(usage, "cache_read_input_tokens", None)} if usage else None,
    }
