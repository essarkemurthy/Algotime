"""trade_engine/strategy_signals.py — Signal generators for the 5 core strategies.

Each class implements generate_signals() which the strategy runner calls every
N seconds. Signals are broadcast via WebSocket and optionally auto-executed as
paper trades.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional
import logging

log = logging.getLogger(__name__)


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class Signal:
    strategy_id: str
    symbol:      str
    action:      str          # BUY_CALL | BUY_PUT | SELL_CALL | SELL_PUT |
                              # ENTER_IRON_CONDOR | SELL_STRANGLE | BUY_STRADDLE |
                              # HEDGE_SHORT | HEDGE_LONG | CLOSE
    rationale:   str
    confidence:  float        # 0.0 – 1.0
    strike:      Optional[int]   = None
    expiry:      Optional[date]  = None
    entry_price: Optional[float] = None
    target_pct:  Optional[float] = None
    sl_pct:      Optional[float] = None
    ts: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "symbol":      self.symbol,
            "action":      self.action,
            "rationale":   self.rationale,
            "confidence":  round(self.confidence, 2),
            "strike":      self.strike,
            "expiry":      self.expiry.isoformat() if self.expiry else None,
            "entry_price": self.entry_price,
            "target_pct":  self.target_pct,
            "sl_pct":      self.sl_pct,
            "ts":          self.ts.strftime("%H:%M:%S"),
        }


# ── 1. 0DTE Expiry-Day Scalper ────────────────────────────────────────────────

class ZeroDTEScalper:
    id          = "zero_dte"
    name        = "0DTE Expiry Scalper"
    risk        = "HIGH"
    description = ("Expiry-day ATM option scalping using VWAP, OI buildup, and "
                   "breakout setups. 4 opportunities per week across indices.")

    # Which weekday (Mon=0) each index expires
    _EXPIRY_WEEKDAY = {"NIFTY": 3, "MIDCPNIFTY": 3, "BANKNIFTY": 2, "FINNIFTY": 1}

    def __init__(self, cfg: dict) -> None:
        self.symbols    = cfg.get("symbols",    ["NIFTY"])
        self.tf         = cfg.get("entry_tf",   "5minute")
        self.target_pct = cfg.get("target_pct", 25)
        self.sl_pct     = cfg.get("sl_pct",     35)
        self.max_trades = cfg.get("max_trades", 3)

        self._vwap_num:   Dict[str, float] = {}
        self._vwap_den:   Dict[str, float] = {}
        self._range_high: Dict[str, float] = {}
        self._range_low:  Dict[str, float] = {}
        self._range_set:  Dict[str, bool]  = {}
        self._trades_today: Dict[str, int] = {}

    def generate_signals(self, session, ltp_cache: dict, db_store) -> List[Signal]:
        today   = date.today()
        weekday = today.weekday()
        signals: List[Signal] = []

        for sym in self.symbols:
            if self._EXPIRY_WEEKDAY.get(sym, 3) != weekday:
                continue
            if self._trades_today.get(sym, 0) >= self.max_trades:
                continue
            ltp = ltp_cache.get(sym)
            if not ltp:
                continue

            # Rolling VWAP (tick-based approximation)
            num = self._vwap_num.get(sym, 0.0) + ltp
            den = self._vwap_den.get(sym, 0.0) + 1
            self._vwap_num[sym] = num
            self._vwap_den[sym] = den
            vwap = num / den

            # Build opening range during first 3 ticks
            if not self._range_set.get(sym):
                self._range_high[sym] = max(self._range_high.get(sym, 0.0), ltp)
                self._range_low[sym]  = min(self._range_low.get(sym, 9e9), ltp)
                if den >= 3:
                    self._range_set[sym] = True
                continue

            high = self._range_high.get(sym, 0.0)
            low  = self._range_low.get(sym, 9e9)

            if ltp > high * 1.001 and ltp > vwap:
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action="BUY_CALL",
                    rationale=f"Breakout above {high:.0f} | LTP {ltp:.0f} > VWAP {vwap:.0f}",
                    confidence=0.75,
                    target_pct=self.target_pct, sl_pct=self.sl_pct,
                ))
                self._trades_today[sym] = self._trades_today.get(sym, 0) + 1

            elif ltp < low * 0.999 and ltp < vwap:
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action="BUY_PUT",
                    rationale=f"Breakdown below {low:.0f} | LTP {ltp:.0f} < VWAP {vwap:.0f}",
                    confidence=0.75,
                    target_pct=self.target_pct, sl_pct=self.sl_pct,
                ))
                self._trades_today[sym] = self._trades_today.get(sym, 0) + 1

        return signals


# ── 2. IVR Iron Condor ────────────────────────────────────────────────────────

class IVRIronCondor:
    id          = "ivr_condor"
    name        = "IVR Iron Condor"
    risk        = "MEDIUM"
    description = ("Sell iron condors when IV Rank > threshold. "
                   "Close at 50% profit or 200% loss.")

    def __init__(self, cfg: dict) -> None:
        self.symbols            = cfg.get("symbols",            ["NIFTY"])
        self.ivr_threshold      = cfg.get("ivr_threshold",      50)
        self.delta_target       = cfg.get("delta_target",       0.25)
        self.profit_target_pct  = cfg.get("profit_target_pct",  50)
        self.sl_pct             = cfg.get("sl_pct",             200)
        self._entered: Dict[str, bool] = {}

    def generate_signals(self, session, ltp_cache: dict, db_store) -> List[Signal]:
        signals: List[Signal] = []
        for sym in self.symbols:
            ivr = self._get_ivr(sym, db_store)
            label = f"IVR={ivr:.0f}" if ivr is not None else "IVR=N/A"

            if not self._entered.get(sym) and ivr is not None and ivr > self.ivr_threshold:
                conf = min(0.95, 0.5 + (ivr - self.ivr_threshold) / 100)
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym,
                    action="ENTER_IRON_CONDOR",
                    rationale=f"{label} > {self.ivr_threshold} — sell premium, defined risk",
                    confidence=conf,
                ))
                self._entered[sym] = True

            elif self._entered.get(sym) and ivr is not None and ivr < 30:
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action="CLOSE",
                    rationale=f"{label} dropped < 30 — IV crush captured, close condor",
                    confidence=0.85,
                ))
                self._entered[sym] = False

        return signals

    def _get_ivr(self, symbol: str, db_store) -> Optional[float]:
        if db_store is None:
            return None
        try:
            df = db_store.get_iv_history(symbol, lookback_days=252)
            if df.empty or len(df) < 30:
                return None
            current  = float(df.iloc[0]["atm_iv"])
            low_52w  = float(df["atm_iv"].min())
            high_52w = float(df["atm_iv"].max())
            if high_52w <= low_52w:
                return None
            return round((current - low_52w) / (high_52w - low_52w) * 100, 1)
        except Exception as exc:
            log.debug("IVR lookup failed %s: %s", symbol, exc)
            return None


# ── 3. VIX Regime Switcher ────────────────────────────────────────────────────

class VIXRegimeSwitcher:
    id          = "vix_regime"
    name        = "VIX Regime Switcher"
    risk        = "MEDIUM"
    description = ("Auto-adapts between option-selling and buying based on "
                   "India VIX. <13→sell, 13–18→condor, >18→buy.")

    def __init__(self, cfg: dict) -> None:
        self.symbols         = cfg.get("symbols",         ["NIFTY"])
        self.sell_threshold  = cfg.get("sell_threshold",  13.0)
        self.buy_threshold   = cfg.get("buy_threshold",   18.0)
        self._last_regime:   Optional[str]   = None
        self._vix_fallback:  Optional[float] = None

    def generate_signals(self, session, ltp_cache: dict, db_store) -> List[Signal]:
        vix = ltp_cache.get("INDIAVIX") or self._vix_fallback
        # Try to fetch VIX from Breeze if not in ltp cache
        if vix is None and session is not None:
            try:
                resp = session.api.get_quotes(
                    stock_code="INDIAVIX", exchange_code="NSE",
                    expiry_date="", product_type="cash",
                    right="", strike_price="",
                )
                if resp.get("Status") == 200 and resp.get("Success"):
                    vix = float(resp["Success"][0]["ltp"])
                    self._vix_fallback = vix
            except Exception:
                pass

        if vix is None:
            return []

        regime = ("SELL" if vix < self.sell_threshold
                  else "BUY" if vix > self.buy_threshold
                  else "CONDOR")

        if regime == self._last_regime:
            return []

        self._last_regime = regime
        _REGIME_MAP = {
            "SELL":   ("SELL_STRANGLE",     f"VIX={vix:.1f} < {self.sell_threshold} — low vol, sell premium"),
            "BUY":    ("BUY_STRADDLE",      f"VIX={vix:.1f} > {self.buy_threshold} — high vol, buy straddle"),
            "CONDOR": ("ENTER_IRON_CONDOR", f"VIX={vix:.1f} in condor zone ({self.sell_threshold}–{self.buy_threshold})"),
        }
        action, rationale = _REGIME_MAP[regime]
        return [
            Signal(strategy_id=self.id, symbol=sym, action=action,
                   rationale=rationale, confidence=0.80)
            for sym in self.symbols
        ]


# ── 4. Gamma Scalper ──────────────────────────────────────────────────────────

class GammaScalper:
    id          = "gamma_scalp"
    name        = "Gamma Scalper"
    risk        = "MEDIUM"
    description = ("Long ATM straddle + delta-neutral futures hedge. "
                   "Profits when realised vol > implied vol.")

    def __init__(self, cfg: dict) -> None:
        self.symbols         = cfg.get("symbols",          ["NIFTY"])
        self.delta_threshold = cfg.get("delta_threshold",  0.15)
        self.max_hedges      = cfg.get("max_hedges",       5)
        self._portfolio_delta: Dict[str, float] = {}
        self._hedge_count:     Dict[str, int]   = {}
        self._straddle_on:     Dict[str, bool]  = {}

    def generate_signals(self, session, ltp_cache: dict, db_store) -> List[Signal]:
        signals: List[Signal] = []
        for sym in self.symbols:
            # Suggest entering the straddle if not already on
            if not self._straddle_on.get(sym):
                ltp = ltp_cache.get(sym)
                if ltp:
                    signals.append(Signal(
                        strategy_id=self.id, symbol=sym, action="BUY_STRADDLE",
                        rationale=f"Enter ATM straddle @ {ltp:.0f} to start gamma-scalp cycle",
                        confidence=0.85,
                    ))
                    self._straddle_on[sym] = True
                continue

            # Hedge when delta threshold breached
            delta = self._portfolio_delta.get(sym, 0.0)
            hedges = self._hedge_count.get(sym, 0)
            if abs(delta) > self.delta_threshold and hedges < self.max_hedges:
                action = "HEDGE_SHORT" if delta > 0 else "HEDGE_LONG"
                lots   = max(1, int(abs(delta) / 0.05))
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action=action,
                    rationale=(f"Portfolio Δ={delta:+.2f} > ±{self.delta_threshold} — "
                               f"{lots} lot futures hedge #{hedges + 1}"),
                    confidence=0.92,
                ))
                self._hedge_count[sym] = hedges + 1
                self._portfolio_delta[sym] = 0.0  # reset after hedge

        return signals

    def update_delta(self, symbol: str, delta: float) -> None:
        self._portfolio_delta[symbol] = delta


# ── 5. Momentum Breakout ──────────────────────────────────────────────────────

class MomentumBreakout:
    id          = "momentum"
    name        = "Momentum Breakout"
    risk        = "MEDIUM"
    description = ("Buy CE/PE when price breaks N-period high/low on 15m chart. "
                   "Works across Nifty 50 stocks.")

    def __init__(self, cfg: dict) -> None:
        self.symbols    = cfg.get("symbols",          ["RELIANCE", "TCS", "INFY"])
        self.lookback   = cfg.get("lookback_periods", 20)
        self.target_pct = cfg.get("target_pct",       40)
        self.sl_pct     = cfg.get("sl_pct",           25)
        self._prices: Dict[str, list] = {}
        self._last_signal: Dict[str, str] = {}

    def generate_signals(self, session, ltp_cache: dict, db_store) -> List[Signal]:
        signals: List[Signal] = []
        for sym in self.symbols:
            ltp = ltp_cache.get(sym)
            if not ltp:
                continue

            prices = self._prices.setdefault(sym, [])
            prices.append(ltp)
            if len(prices) > self.lookback + 1:
                prices.pop(0)
            if len(prices) < self.lookback:
                continue

            window      = prices[:-1]
            period_high = max(window)
            period_low  = min(window)

            if ltp > period_high and self._last_signal.get(sym) != "BUY_CALL":
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action="BUY_CALL",
                    rationale=(f"{sym} breaks {self.lookback}-period high {period_high:.0f} "
                               f"→ momentum long (LTP {ltp:.0f})"),
                    confidence=0.72,
                    target_pct=self.target_pct, sl_pct=self.sl_pct,
                ))
                self._last_signal[sym] = "BUY_CALL"

            elif ltp < period_low and self._last_signal.get(sym) != "BUY_PUT":
                signals.append(Signal(
                    strategy_id=self.id, symbol=sym, action="BUY_PUT",
                    rationale=(f"{sym} breaks {self.lookback}-period low {period_low:.0f} "
                               f"→ momentum short (LTP {ltp:.0f})"),
                    confidence=0.72,
                    target_pct=self.target_pct, sl_pct=self.sl_pct,
                ))
                self._last_signal[sym] = "BUY_PUT"

            else:
                # Reset so the same direction can re-trigger after a pause
                if abs(ltp - period_high) / period_high > 0.005:
                    self._last_signal.pop(sym, None)

        return signals


# ── Registry ──────────────────────────────────────────────────────────────────

STRATEGY_REGISTRY = {
    ZeroDTEScalper.id:   ZeroDTEScalper,
    IVRIronCondor.id:    IVRIronCondor,
    VIXRegimeSwitcher.id: VIXRegimeSwitcher,
    GammaScalper.id:     GammaScalper,
    MomentumBreakout.id: MomentumBreakout,
}
