"""
suggestions.py — Morning Brief: AI-powered trade suggestions with approve/skip flow.

Uses Claude Haiku for suggestions when ANTHROPIC_API_KEY is set;
falls back to rule-based logic otherwise.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

log = logging.getLogger("suggestions")

# ── JSON schema for Claude to follow ─────────────────────────────────────────

_TRADE_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "conviction", "watch_stock", "exchange", "product",
                 "action", "quantity", "order_type", "trigger_price",
                 "trigger_direction", "target", "stop_loss", "max_spend", "rationale"],
    "properties": {
        "id":                 {"type": "string"},
        "name":               {"type": "string"},
        "conviction":         {"type": "string", "enum": ["high", "medium", "low"]},
        "watch_stock":        {"type": "string"},
        "exchange":           {"type": "string"},
        "product":            {"type": "string", "enum": ["options", "cash"]},
        "right":              {"type": "string", "enum": ["CE", "PE"]},
        "strike":             {"type": "integer"},
        "expiry":             {"type": "string"},
        "action":             {"type": "string", "enum": ["buy", "sell"]},
        "quantity":           {"type": "integer"},
        "order_type":         {"type": "string", "enum": ["market", "limit"]},
        "trigger_price":      {"type": "number"},
        "trigger_direction":  {"type": "string", "enum": ["above", "below"]},
        "target":             {"type": "number"},
        "stop_loss":          {"type": "number"},
        "max_spend":          {"type": "number"},
        "rationale":          {"type": "string"},
    },
    "additionalProperties": False,
}

_BRIEF_SCHEMA = {
    "type": "object",
    "required": ["bias", "summary", "trades"],
    "properties": {
        "bias":    {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "summary": {"type": "string"},
        "trades":  {"type": "array", "items": _TRADE_SCHEMA, "minItems": 1, "maxItems": 4},
    },
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
You are a professional NSE options and equity trading advisor for Indian markets.
Given live LTP data (price levels for NIFTY and key stocks), generate 2-4 actionable intraday trade suggestions.

Output rules:
- Suggest only trades with clear setups and defined risk/reward
- Use options (exchange NFO, product "options") for directional leveraged plays
- Use cash equity (exchange NSE, product "cash") for simpler setups
- For options: always supply right (CE/PE), strike (round number nearest to current price), expiry (YYYY-MM-DD nearest weekly Thursday)
- trigger_price: exact level the trader should watch and act on
- trigger_direction: "above" if trade fires when price rises through trigger, "below" if fires on dip
- action: "buy" to go long, "sell" to short
- quantity: realistic lot — 75 for NIFTY options, 50-200 for individual stocks
- max_spend: estimated maximum premium/capital at risk (₹) for this trade
- rationale: ≤35 words explaining the setup

Output ONLY valid JSON matching the schema. No extra text."""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TradeIdea:
    id:                str
    name:              str
    conviction:        str           # high | medium | low
    watch_stock:       str
    exchange:          str           # NSE | NFO
    product:           str           # options | cash
    action:            str           # buy | sell
    quantity:          int
    order_type:        str           # market | limit
    trigger_price:     float
    trigger_direction: str           # above | below
    target:            float
    stop_loss:         float
    max_spend:         float
    rationale:         str
    right:             Optional[str] = None   # CE | PE (options)
    strike:            Optional[int] = None
    expiry:            Optional[str] = None   # YYYY-MM-DD
    status:            str           = "pending"   # pending | approved | skipped


@dataclass
class MorningBrief:
    bias:         str
    summary:      str
    trades:       List[TradeIdea]
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    source:       str = "ai"   # "ai" | "rules"


# ── Engine ────────────────────────────────────────────────────────────────────

class SuggestionEngine:
    """Generates morning trade suggestions and tracks their approve/skip state."""

    def __init__(self, ltp_cache: dict) -> None:
        self._ltp   = ltp_cache
        self._brief: Optional[MorningBrief] = None

    def generate(self) -> MorningBrief:
        """Generate (or refresh) morning brief. Returns MorningBrief."""
        snapshot = self._build_snapshot()
        try:
            if os.getenv("ANTHROPIC_API_KEY"):
                self._brief = self._claude_suggestions(snapshot)
            else:
                self._brief = self._rule_based_suggestions(snapshot)
        except Exception as exc:
            log.warning("Claude suggestions failed (%s) — using rule-based fallback", exc)
            self._brief = self._rule_based_suggestions(snapshot)
        log.info("Morning brief generated (%s): bias=%s, %d trades",
                 self._brief.source, self._brief.bias, len(self._brief.trades))
        return self._brief

    def get_brief(self) -> Optional[MorningBrief]:
        return self._brief

    def approve(self, trade_id: str) -> Optional[TradeIdea]:
        if self._brief:
            for t in self._brief.trades:
                if t.id == trade_id:
                    t.status = "approved"
                    return t
        return None

    def skip(self, trade_id: str) -> bool:
        if self._brief:
            for t in self._brief.trades:
                if t.id == trade_id:
                    t.status = "skipped"
                    return True
        return False

    # ── private ───────────────────────────────────────────────────────────────

    def _build_snapshot(self) -> dict:
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "ltp":       {k: round(v, 2) for k, v in self._ltp.items()},
        }

    def _claude_suggestions(self, snapshot: dict) -> MorningBrief:
        import anthropic
        client = anthropic.Anthropic()

        user_content = (
            f"Market snapshot — {snapshot['timestamp']}\n"
            f"Live LTPs (₹):\n"
            + "\n".join(f"  {k}: {v}" for k, v in snapshot["ltp"].items())
            + f"\n\nNearest weekly expiry: {_nearest_thursday()}"
            + "\n\nGenerate 2-4 trade suggestions."
        )

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{
                "type":          "text",
                "text":          _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )

        raw  = json.loads(resp.content[0].text)
        return self._parse_response(raw, source="ai")

    def _rule_based_suggestions(self, snapshot: dict) -> MorningBrief:
        prices = snapshot["ltp"]
        nifty  = prices.get("NIFTY", 23500)
        expiry = _nearest_thursday()
        atm    = int(round(nifty / 50) * 50)

        if nifty >= 23500:
            bias   = "bullish"
            summary = (
                f"NIFTY @ ₹{nifty:,.0f} — above key level. "
                "Bullish bias: watch for breakout continuation."
            )
            trades = [
                TradeIdea(
                    id="rb_1", name="NIFTY Call Breakout",
                    conviction="medium",
                    watch_stock="NIFTY", exchange="NFO", product="options",
                    right="CE", strike=atm + 100, expiry=expiry,
                    action="buy", quantity=75, order_type="market",
                    trigger_price=round(nifty * 1.002, -1),
                    trigger_direction="above",
                    target=round(nifty * 1.008, -1),
                    stop_loss=round(nifty * 0.995, -1),
                    max_spend=6000,
                    rationale="Bullish momentum breakout play; call buy on price moving above trigger.",
                ),
                TradeIdea(
                    id="rb_2", name="INFY Long (equity)",
                    conviction="low",
                    watch_stock="INFY", exchange="NSE", product="cash",
                    action="buy", quantity=100, order_type="limit",
                    trigger_price=round(prices.get("INFY", 1500) * 0.998, 1),
                    trigger_direction="below",
                    target=round(prices.get("INFY", 1500) * 1.006, 1),
                    stop_loss=round(prices.get("INFY", 1500) * 0.993, 1),
                    max_spend=15000,
                    rationale="Intraday long on dip to support; broader market bullish bias.",
                ),
            ]
        else:
            bias   = "bearish"
            summary = (
                f"NIFTY @ ₹{nifty:,.0f} — below key 23,500 level. "
                "Bearish bias: watch for breakdown continuation."
            )
            trades = [
                TradeIdea(
                    id="rb_1", name="NIFTY Put Breakdown",
                    conviction="medium",
                    watch_stock="NIFTY", exchange="NFO", product="options",
                    right="PE", strike=atm - 100, expiry=expiry,
                    action="buy", quantity=75, order_type="market",
                    trigger_price=round(nifty * 0.998, -1),
                    trigger_direction="below",
                    target=round(nifty * 0.992, -1),
                    stop_loss=round(nifty * 1.004, -1),
                    max_spend=6000,
                    rationale="Bearish momentum breakdown play; put buy on price moving below trigger.",
                ),
                TradeIdea(
                    id="rb_2", name="ONGC Short (equity)",
                    conviction="low",
                    watch_stock="ONGC", exchange="NSE", product="cash",
                    action="sell", quantity=200, order_type="limit",
                    trigger_price=round(prices.get("ONGC", 260) * 1.003, 1),
                    trigger_direction="above",
                    target=round(prices.get("ONGC", 260) * 0.994, 1),
                    stop_loss=round(prices.get("ONGC", 260) * 1.007, 1),
                    max_spend=5000,
                    rationale="Short on bounce; weak broader market and sector underperformance.",
                ),
            ]

        return MorningBrief(bias=bias, summary=summary, trades=trades, source="rules")

    def _parse_response(self, raw: dict, source: str = "ai") -> MorningBrief:
        trades = []
        for i, t in enumerate(raw.get("trades", [])):
            trades.append(TradeIdea(
                id                = t.get("id", f"ai_{i+1}"),
                name              = t.get("name", f"Trade {i+1}"),
                conviction        = t.get("conviction", "medium"),
                watch_stock       = t.get("watch_stock", "NIFTY"),
                exchange          = t.get("exchange", "NFO"),
                product           = t.get("product", "options"),
                right             = t.get("right"),
                strike            = t.get("strike"),
                expiry            = t.get("expiry"),
                action            = t.get("action", "buy"),
                quantity          = int(t.get("quantity", 75)),
                order_type        = t.get("order_type", "market"),
                trigger_price     = float(t.get("trigger_price", 0)),
                trigger_direction = t.get("trigger_direction", "above"),
                target            = float(t.get("target", 0)),
                stop_loss         = float(t.get("stop_loss", 0)),
                max_spend         = float(t.get("max_spend", 5000)),
                rationale         = t.get("rationale", ""),
            ))
        return MorningBrief(
            bias    = raw.get("bias", "neutral"),
            summary = raw.get("summary", ""),
            trades  = trades,
            source  = source,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nearest_thursday() -> str:
    d = date.today()
    days_ahead = (3 - d.weekday()) % 7   # 3 = Thursday
    if days_ahead == 0:
        days_ahead = 7
    return (d + timedelta(days=days_ahead)).isoformat()
