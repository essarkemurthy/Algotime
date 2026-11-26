"""
chat_agent.py — "ask the desk" chatbot over the app's live state.

Pure functions plus one thin Claude call, so everything except the network is
unit-testable. `app.py` collects the raw state (`/api/status`, paper engine,
algo engine, live bridge, LTP cache, today's journal) and hands it to
`build_snapshot()`; the trimmed snapshot rides inside the LAST user message only,
so the (cached) system prompt and the earlier turns stay byte-stable.

The bot is read-only: it explains, it never places, exits, arms or toggles
anything. Real orders stay behind the two gates in live_orders.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover
    _IST = None

DEFAULT_MODEL = "claude-opus-5-5"
MODEL = os.environ.get("CHAT_MODEL", DEFAULT_MODEL)
MAX_TOKENS = 2000
MAX_HISTORY_TURNS = 20          # user+assistant messages kept from the browser
MAX_TURN_CHARS = 4000
MAX_QUESTION_CHARS = 2000
MAX_SIGNALS = 12
MAX_TRADES_TODAY = 30
INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX",
                 "NIFTYNEXT50", "CNXIT", "INDIAVIX")

SYSTEM_PROMPT = """You are the desk assistant inside Algotime, a personal Indian equity and index-options
trading dashboard (ICICI Breeze feed, NSE/BSE, times in IST). The operator asks you about the
current situation; a JSON snapshot of the app's state at the moment of the question is attached
inside <situation> tags in their message.

Answer only from the snapshot and the conversation. If something is not in the snapshot, say it is
not available rather than guessing. Quote the numbers you rely on (rupees with the ₹ sign, two
decimals for prices, whole rupees for P&L) and name the strategy, instrument and side when you
talk about a position.

Keep these distinctions sharp:
- "paper" positions are simulated (paper_manual = hand-placed on the paper page, paper_algo = the
  strategy engine). Real money moves only through the live order bridge; say whether it is armed,
  in dry-run, or disarmed before calling anything "live".
- unrealised P&L (open positions, marked at the last traded price) versus realised P&L (closed).
- the paper record in this app is net negative overall; never describe any strategy as reliably
  profitable, and do not predict where a price or P&L will go.

You cannot place, exit, arm or toggle anything; if asked to act, say so and point to the control on
the page. Be concise: lead with the direct answer, then the supporting numbers, in plain prose or a
short list. No preamble."""


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


def build_snapshot(*, status: Optional[dict] = None, funds: Optional[dict] = None,
                   ltp: Optional[Dict[str, float]] = None, prev_close: Optional[Dict[str, float]] = None,
                   algo: Optional[dict] = None, paper_summary: Optional[dict] = None,
                   manual_positions: Optional[dict] = None, live: Optional[dict] = None,
                   trades_today: Optional[Sequence[dict]] = None,
                   alltime: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    """Trim the app's raw state to what a question about 'the position' needs."""
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
    return anthropic.Anthropic(max_retries=2, timeout=60.0)


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
        output_config={"effort": "low"},
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
