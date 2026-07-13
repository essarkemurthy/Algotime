"""
paper_algo.py — auto-execute intraday signals on the paper trading account.

Bridges the read-only signal engine (signals/) to the PaperTrader: when an
enabled strategy fires, it opens a paper position with an ATR-based stop-loss and
target, then manages the exit on every tick and force-squares-off near the close.
Each strategy trades at most one position per symbol at a time, and P&L is
attributed per strategy for the dashboard.

Threading: on_signal / on_tick are invoked from the Breeze SDK tick thread; an
internal lock guards the algo's own bookkeeping. Fills go through PaperTrader
(same account the manual UI uses).
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as time_t
from typing import Deque, Dict, List, Optional, Tuple

LONG = "LONG"

# Underlyings that have a tradable weekly option chain (mirrors app._CHAIN_META).
OPTION_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"})
# Contract lot sizes — one place to edit if the exchange revises them.
OPTION_LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65,
                   "MIDCPNIFTY": 120, "SENSEX": 20}

log = logging.getLogger(__name__)


def _fmt_expiry(expiry: str) -> str:
    """'2026-07-10' → '10-Jul' for compact instrument labels."""
    try:
        return datetime.strptime(str(expiry)[:10], "%Y-%m-%d").strftime("%d-%b")
    except (ValueError, TypeError):
        return str(expiry or "")


# Strategies enabled by default — the only ones net-positive (gross) over a
# 1-year, 27-symbol 5m backtest: VWAP_TREND (PF 1.06), ORB (1.05), VWAP_REV
# (1.02). See scripts/backtest_strategies.py. The rest (DONCHIAN, SUPERTREND,
# BB_REV, EMA_X, RSI2) backtested ≤ break-even and stay OFF until toggled on.
# NOTE: edges are thin and transaction costs are NOT modelled — treat as a
# paper-trading research baseline, not a live edge.
DEFAULT_ENABLED = ("VWAP_TREND", "ORB", "VWAP_REV", "VWAP_ORB")
ALL_STRATEGIES = ("ORB", "VWAP_REV", "VWAP_ORB", "EMA_X", "SUPERTREND", "VWAP_TREND",
                  "RSI2", "BB_REV", "DONCHIAN")


@dataclass
class AlgoConfig:
    capital_per_trade: float = 100_000.0   # ₹ notional deployed per entry
    sl_atr: float = 1.5                    # stop distance in ATR multiples
    tp_atr: float = 2.0                    # target distance in ATR multiples
    max_positions: int = 12                # cap concurrent open algo positions
    square_off: time_t = field(default_factory=lambda: time_t(15, 15))
    # Regime filter — validated to improve every strategy (scripts/backtest_better.py):
    # only take trend-aligned entries inside the active window with enough vol.
    regime_filter: bool = True
    entry_start: time_t = field(default_factory=lambda: time_t(9, 45))
    entry_end: time_t = field(default_factory=lambda: time_t(14, 0))
    atr_pct_floor: float = 0.0010          # 0.10% ATR/price minimum
    # ── Master engine gates (launched from the UI) ─────────────────────────────
    # Two independent algo engines. Equity signals trade cash only when the
    # intraday engine is on; index-underlying signals trade the ATM option only
    # when the options engine is on. Turning a gate off stops *new* entries;
    # open positions keep being managed (SL/TP/square-off).
    trade_intraday: bool = False           # cash-equity auto-trading (launch from UI)
    # When on, signals on an index underlying buy the ATM CE (LONG) / PE (SHORT).
    # SL/TP are on the *premium* (ATR is on the underlying, not the option), so
    # options use plain % of the entry premium.
    trade_options: bool = False
    option_underlyings: frozenset = OPTION_UNDERLYINGS
    option_sl_pct: float = 0.30            # stop at −30% of entry premium
    option_tp_pct: float = 0.50            # target at +50% of entry premium
    option_lot_size: Dict[str, int] = field(
        default_factory=lambda: dict(OPTION_LOT_SIZE))


@dataclass
class _OpenPos:
    symbol: str
    strategy: str
    direction: str      # LONG | SHORT (of the underlying signal)
    qty: int
    entry: float
    sl: float
    tp: float
    opened_at: datetime
    product: str = "cash"               # cash | options
    instrument: str = ""                # human label (equity symbol or option)
    signal_ts: Optional[datetime] = None
    stock: str = ""                     # underlying stock_code (for exit order)
    exchange: str = "NSE"               # exit-order exchange (NSE cash / NFO|BFO opt)
    right: Optional[str] = None         # CE | PE (options only)
    strike: Optional[int] = None
    expiry: Optional[str] = None


class AlgoPaperTrader:
    def __init__(self, paper, ltp_cache: Dict[str, float],
                 cfg: Optional[AlgoConfig] = None, broadcast=None, store=None) -> None:
        self._paper = paper
        self._ltp = ltp_cache
        self.cfg = cfg or AlgoConfig()
        self._broadcast = broadcast          # optional callable(dict)
        self.store = store                   # optional DataStore for persistence
        self._lock = threading.Lock()
        self._siglock = threading.Lock()     # guards the signal-decision deque
        self.enabled: set = set(DEFAULT_ENABLED)
        self._open: Dict[Tuple[str, str], _OpenPos] = {}   # (symbol, strategy) → pos
        self._closed: List[dict] = []        # closed algo trades (P&L attribution)
        # Every signal the algo sees, with its decision + timing — powers the
        # signals report (generation time → execution time → lag).
        self._signals: Deque[dict] = deque(maxlen=500)

    # ── controls ──────────────────────────────────────────────────────────────

    def set_enabled(self, strategy: str, on: bool) -> None:
        with self._lock:
            if on:
                self.enabled.add(strategy)
            else:
                self.enabled.discard(strategy)

    def _size(self, price: float) -> int:
        if price <= 0:
            return 0
        return max(0, int(self.cfg.capital_per_trade // price))

    def _passes_filter(self, sig) -> bool:
        """Regime filter (backtest-validated): trend-aligned entry, inside the
        active window, with sufficient volatility."""
        if sig.direction == LONG and sig.trigger_price <= sig.vwap:
            return False
        if sig.direction != LONG and sig.trigger_price >= sig.vwap:
            return False
        t = sig.ts.time() if hasattr(sig.ts, "time") else datetime.now().time()
        if not (self.cfg.entry_start <= t <= self.cfg.entry_end):
            return False
        if sig.trigger_price > 0 and sig.atr / sig.trigger_price < self.cfg.atr_pct_floor:
            return False
        return True

    # ── signal decision log (powers the signals report) ───────────────────────

    def _decision_base(self, sig) -> dict:
        now = datetime.now()
        sig_ts = sig.ts if isinstance(sig.ts, datetime) else None
        return {
            "signal_ts":     sig_ts.strftime("%H:%M:%S") if sig_ts else None,
            "received_at":   now.strftime("%H:%M:%S"),
            "strategy":      sig.strategy,
            "symbol":        sig.symbol,
            "direction":     sig.direction,
            "trigger_price": round(float(sig.trigger_price), 2),
            "vwap":          round(float(sig.vwap), 2) if sig.vwap == sig.vwap else None,
            "atr":           round(float(sig.atr), 2) if sig.atr == sig.atr else None,
            "product":       "cash",
            "instrument":    None,
            "decision":      None,
            "reason":        None,
            "entry_price":   None,
            "entry_time":    None,
            "exec_lag_sec":  None,
        }

    def _log_decision(self, sig, base: dict, decision: str, reason: str, **extra) -> dict:
        rec = dict(base)
        rec["decision"] = decision
        rec["reason"] = reason
        rec.update(extra)
        with self._siglock:
            self._signals.appendleft(rec)
        self._persist_decision(sig, rec)
        return rec

    def _finalize_option_decision(self, sig, decision: str, reason: str, **extra) -> dict:
        """Update the PENDING record left by on_signal's option-routing branch
        (or append a fresh one if none is found)."""
        with self._siglock:
            for rec in self._signals:            # newest first
                if (rec.get("decision") == "PENDING"
                        and rec["symbol"] == sig.symbol
                        and rec["strategy"] == sig.strategy):
                    rec["decision"] = decision
                    rec["reason"] = reason
                    rec.update(extra)
                    self._persist_decision(sig, rec)
                    return rec
        return self._log_decision(sig, self._decision_base(sig), decision, reason, **extra)

    def _persist_decision(self, sig, rec: dict) -> None:
        """Write a terminal (EXECUTED/SKIPPED) decision to the DB for the reports.
        Transient PENDING rows are not persisted. Never raises into the caller."""
        if self.store is None or rec.get("decision") not in ("EXECUTED", "SKIPPED"):
            return
        try:
            sig_ts = sig.ts if isinstance(sig.ts, datetime) else None
            td = (getattr(sig, "trade_date", None)
                  or (sig_ts.date() if sig_ts else datetime.now().date()))
            now = datetime.now()
            self.store.insert_signal_decision({
                "signal_ts": sig_ts, "received_ts": now, "trade_date": td,
                "strategy": rec["strategy"], "symbol": rec["symbol"],
                "direction": rec["direction"], "trigger_price": rec["trigger_price"],
                "vwap": rec["vwap"], "atr": rec["atr"], "product": rec["product"],
                "decision": rec["decision"], "reason": rec["reason"],
                "instrument": rec["instrument"], "entry_price": rec["entry_price"],
                "entry_ts": now if rec["decision"] == "EXECUTED" else None,
                "exec_lag_sec": rec["exec_lag_sec"],
            })
        except Exception as exc:
            log.debug("paper decision persist failed: %s", exc)

    # ── entry: a strategy fired ───────────────────────────────────────────────

    def wants_option(self, sig) -> bool:
        """True if this signal should be routed to an option trade (index chain,
        options armed). app.py uses this to trigger the async resolve+subscribe."""
        return (self.cfg.trade_options
                and sig.strategy in self.enabled
                and sig.symbol in self.cfg.option_underlyings
                and sig.atr == sig.atr and sig.atr > 0
                and (not self.cfg.regime_filter or self._passes_filter(sig)))

    def on_signal(self, sig) -> None:
        """sig is a signals.detectors.Signal (has symbol/strategy/direction/atr).

        Records a decision for *every* signal (executed or skipped, with reason)
        so the signals report can show generation → execution timing. When
        options are armed and the underlying has a chain, the signal is marked
        PENDING here and the actual option entry is done by app.py (which does the
        blocking chain-resolve + WS-subscribe off the tick thread) via
        open_option_position()."""
        strat = sig.strategy
        base = self._decision_base(sig)
        if strat not in self.enabled:
            self._log_decision(sig, base, "SKIPPED", "not_enabled")
            return
        atr = sig.atr
        if not (atr == atr and atr > 0):     # need a finite, positive ATR
            self._log_decision(sig, base, "SKIPPED", "no_atr")
            return
        if self.cfg.regime_filter and not self._passes_filter(sig):
            self._log_decision(sig, base, "SKIPPED", "filter")
            return
        # Master routing: index underlyings → options engine (never traded as
        # cash — you can't buy the spot index); equities → intraday cash engine.
        if sig.symbol in self.cfg.option_underlyings:
            if self.cfg.trade_options:
                # app.py finalises the entry (async chain resolve + subscribe).
                self._log_decision(sig, base, "PENDING", "routed_option", product="options")
            else:
                self._log_decision(sig, base, "SKIPPED", "options_algo_off", product="options")
            return
        if not self.cfg.trade_intraday:
            self._log_decision(sig, base, "SKIPPED", "intraday_algo_off")
            return
        key = (sig.symbol, strat)
        with self._lock:
            if key in self._open:
                self._log_decision(sig, base, "SKIPPED", "duplicate")
                return                        # already in a trade for this pair
            if len(self._open) >= self.cfg.max_positions:
                self._log_decision(sig, base, "SKIPPED", "max_positions")
                return
            price = self._ltp.get(sig.symbol, sig.trigger_price)
            qty = self._size(price)
            if qty <= 0:
                self._log_decision(sig, base, "SKIPPED", "zero_qty")
                return
            action = "buy" if sig.direction == "LONG" else "sell"
            try:
                order = self._paper.place_order(
                    stock=sig.symbol, exchange="NSE", product="cash",
                    action=action, qty=qty, order_type="market", price=0,
                    ltp_cache=self._ltp)
            except Exception as exc:
                log.warning("Algo entry failed %s %s: %s", sig.symbol, strat, exc)
                self._log_decision(sig, base, "SKIPPED", "entry_failed")
                return
            if not order:
                self._log_decision(sig, base, "SKIPPED", "entry_failed")
                return
            fill = float(order.fill_price)
            if sig.direction == "LONG":
                sl, tp = fill - self.cfg.sl_atr * atr, fill + self.cfg.tp_atr * atr
            else:
                sl, tp = fill + self.cfg.sl_atr * atr, fill - self.cfg.tp_atr * atr
            self._open[key] = _OpenPos(
                symbol=sig.symbol, strategy=strat, direction=sig.direction, qty=qty,
                entry=fill, sl=sl, tp=tp, opened_at=datetime.now(),
                product="cash", instrument=sig.symbol,
                signal_ts=sig.ts if isinstance(sig.ts, datetime) else None,
                stock=sig.symbol, exchange="NSE")
            lag = ((datetime.now() - sig.ts).total_seconds()
                   if isinstance(sig.ts, datetime) else None)
            self._log_decision(sig, base, "EXECUTED", "cash_entry", instrument=sig.symbol,
                               entry_price=round(fill, 2),
                               entry_time=datetime.now().strftime("%H:%M:%S"),
                               exec_lag_sec=round(lag, 1) if lag is not None else None)
            log.info("ALGO ENTRY %s %s %s qty=%d @ %.2f (SL %.2f TP %.2f)",
                     strat, sig.direction, sig.symbol, qty, fill, sl, tp)
        self._emit()

    # ── entry: buy the ATM option (called by app.py after async resolve) ───────

    def open_option_position(self, sig, contract: dict) -> bool:
        """Buy the ATM CE (LONG signal) / PE (SHORT signal) for an index signal.

        `contract` = {stock, right ('CE'|'PE'), strike, expiry ('YYYY-MM-DD'),
        premium, exchange}. Long-premium only; SL/TP are % of the entry premium.
        """
        strat = sig.strategy
        stock = contract["stock"]
        right = contract["right"]
        strike = int(contract["strike"])
        expiry = str(contract["expiry"])
        exch = contract.get("exchange", "NFO")
        premium = float(contract.get("premium") or 0.0)
        option_symbol = f"{stock}_{right}_{strike}_{expiry}"
        label = f"{stock} {strike} {right} {_fmt_expiry(expiry)}"

        if premium <= 0:
            self._finalize_option_decision(sig, "SKIPPED", "no_premium",
                                           product="options", instrument=label)
            return False
        lot = self.cfg.option_lot_size.get(stock, 1)
        lots = max(1, int(self.cfg.capital_per_trade // (premium * lot)))
        qty = lots * lot
        key = (option_symbol, strat)
        with self._lock:
            if key in self._open:
                self._finalize_option_decision(sig, "SKIPPED", "duplicate",
                                               product="options", instrument=label)
                return False
            if len(self._open) >= self.cfg.max_positions:
                self._finalize_option_decision(sig, "SKIPPED", "max_positions",
                                               product="options", instrument=label)
                return False
            try:
                order = self._paper.place_order(
                    stock=stock, exchange=exch, product="options",
                    action="buy", qty=qty, order_type="limit", price=premium,
                    ltp_cache=self._ltp, right=right, strike=strike, expiry=expiry)
            except Exception as exc:
                log.warning("Algo option entry failed %s %s: %s", option_symbol, strat, exc)
                self._finalize_option_decision(sig, "SKIPPED", "entry_failed",
                                               product="options", instrument=label)
                return False
            if not order:
                self._finalize_option_decision(sig, "SKIPPED", "entry_failed",
                                               product="options", instrument=label)
                return False
            fill = float(order.fill_price)
            sl = round(fill * (1 - self.cfg.option_sl_pct), 2)
            tp = round(fill * (1 + self.cfg.option_tp_pct), 2)
            self._open[key] = _OpenPos(
                symbol=option_symbol, strategy=strat, direction=sig.direction, qty=qty,
                entry=fill, sl=sl, tp=tp, opened_at=datetime.now(),
                product="options", instrument=label,
                signal_ts=sig.ts if isinstance(sig.ts, datetime) else None,
                stock=stock, exchange=exch, right=right, strike=strike, expiry=expiry)
            lag = ((datetime.now() - sig.ts).total_seconds()
                   if isinstance(sig.ts, datetime) else None)
            self._finalize_option_decision(
                sig, "EXECUTED", "option_entry", product="options", instrument=label,
                entry_price=round(fill, 2), entry_time=datetime.now().strftime("%H:%M:%S"),
                exec_lag_sec=round(lag, 1) if lag is not None else None)
            log.info("ALGO OPT ENTRY %s %s %s qty=%d @ %.2f (SL %.2f TP %.2f)",
                     strat, sig.direction, label, qty, fill, sl, tp)
        self._emit()
        return True

    # ── exit management: every tick ───────────────────────────────────────────

    def on_tick(self, symbol: str, ltp: float) -> None:
        hits: List[Tuple[Tuple[str, str], str]] = []
        with self._lock:
            for key, pos in self._open.items():
                if pos.symbol != symbol:
                    continue
                # Options are always long the premium (buy CE/PE), so they use the
                # long comparison regardless of the underlying signal direction.
                long_exposure = pos.product == "options" or pos.direction == "LONG"
                if long_exposure:
                    if ltp <= pos.sl:   hits.append((key, "SL"))
                    elif ltp >= pos.tp: hits.append((key, "TP"))
                else:
                    if ltp >= pos.sl:   hits.append((key, "SL"))
                    elif ltp <= pos.tp: hits.append((key, "TP"))
        for key, reason in hits:
            self._close(key, reason)

    def square_off_all(self, reason: str = "EOD") -> None:
        for key in list(self._open.keys()):
            self._close(key, reason)

    def _close(self, key: Tuple[str, str], reason: str) -> None:
        with self._lock:
            pos = self._open.pop(key, None)
        if pos is None:
            return
        is_option = pos.product == "options"
        # Options: we are long the premium → sell to close. Cash: sell a long / buy a short.
        action = "sell" if (is_option or pos.direction == "LONG") else "buy"
        try:
            if is_option:
                order = self._paper.place_order(
                    stock=pos.stock, exchange=pos.exchange, product="options",
                    action=action, qty=pos.qty, order_type="market", price=0,
                    ltp_cache=self._ltp, right=pos.right, strike=pos.strike,
                    expiry=pos.expiry)
            else:
                order = self._paper.place_order(
                    stock=pos.stock or pos.symbol, exchange=pos.exchange, product="cash",
                    action=action, qty=pos.qty, order_type="market", price=0,
                    ltp_cache=self._ltp)
        except Exception as exc:
            log.warning("Algo exit failed %s %s: %s", pos.symbol, pos.strategy, exc)
            with self._lock:                  # put it back to retry next tick
                self._open[key] = pos
            return
        exit_price = float(order.fill_price) if order else self._ltp.get(pos.symbol, pos.entry)
        # Long the premium (options) or long cash → +(exit-entry); short cash → +(entry-exit).
        if is_option or pos.direction == "LONG":
            pnl = (exit_price - pos.entry) * pos.qty
        else:
            pnl = (pos.entry - exit_price) * pos.qty
        self._closed.append({
            "symbol": pos.symbol, "strategy": pos.strategy, "direction": pos.direction,
            "product": pos.product, "instrument": pos.instrument or pos.symbol,
            "right": pos.right, "strike": pos.strike, "expiry": pos.expiry,
            "qty": pos.qty, "entry": round(pos.entry, 2), "exit": round(exit_price, 2),
            "pnl": round(pnl, 2), "reason": reason,
            "opened_at": pos.opened_at.strftime("%H:%M:%S"),
            "closed_at": datetime.now().strftime("%H:%M:%S"),
        })
        log.info("ALGO EXIT  %s %s %s qty=%d @ %.2f  %s  P&L %.2f",
                 pos.strategy, pos.direction, pos.instrument or pos.symbol,
                 pos.qty, exit_price, reason, pnl)
        self._persist_trade(pos, exit_price, pnl, reason)
        self._emit()

    def _persist_trade(self, pos, exit_price: float, pnl: float, reason: str) -> None:
        """Persist a closed trade for the DB-backed period reports. Never raises."""
        if self.store is None:
            return
        try:
            closed = datetime.now()
            self.store.insert_paper_trade({
                "opened_ts": pos.opened_at, "closed_ts": closed,
                "trade_date": pos.opened_at.date(), "source": "Algo",
                "strategy": pos.strategy, "product": pos.product, "symbol": pos.symbol,
                "instrument": pos.instrument or pos.symbol, "direction": pos.direction,
                "right": pos.right, "strike": pos.strike, "expiry": pos.expiry,
                "qty": pos.qty, "entry": round(pos.entry, 2),
                "exit": round(exit_price, 2), "pnl": round(pnl, 2), "reason": reason,
            })
        except Exception as exc:
            log.debug("paper trade persist failed: %s", exc)

    # ── time-based square-off, called from the app loop ───────────────────────

    def check_square_off(self, now: Optional[time_t] = None) -> None:
        now = now or datetime.now().time()
        if self._open and now >= self.cfg.square_off:
            log.info("ALGO square-off at %s — flattening %d positions",
                     now.strftime("%H:%M"), len(self._open))
            self.square_off_all("SQUARE_OFF")

    # ── state for the UI ──────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            per: Dict[str, dict] = {}
            for s in ALL_STRATEGIES:
                per[s] = {"strategy": s, "enabled": s in self.enabled,
                          "open": 0, "closed": 0, "wins": 0, "pnl": 0.0}
            for pos in self._open.values():
                per[pos.strategy]["open"] += 1
            for t in self._closed:
                d = per[t["strategy"]]
                d["closed"] += 1
                d["pnl"] += t["pnl"]
                if t["pnl"] > 0:
                    d["wins"] += 1
            open_list = []
            for p in self._open.values():
                ltp = self._ltp.get(p.symbol, p.entry)
                # Options + long cash → +(ltp-entry); short cash → +(entry-ltp).
                if p.product == "options" or p.direction == "LONG":
                    upnl = (ltp - p.entry) * p.qty
                else:
                    upnl = (p.entry - ltp) * p.qty
                open_list.append({
                    "symbol": p.symbol, "strategy": p.strategy, "direction": p.direction,
                    "product": p.product, "instrument": p.instrument or p.symbol,
                    "right": p.right, "strike": p.strike, "expiry": p.expiry,
                    "qty": p.qty, "entry": round(p.entry, 2), "sl": round(p.sl, 2),
                    "tp": round(p.tp, 2), "ltp": round(ltp, 2), "upnl": round(upnl, 2),
                    "opened_at": p.opened_at.strftime("%H:%M:%S"),
                })
            total_realised = round(sum(t["pnl"] for t in self._closed), 2)
            # Outcome tallies for the report stat cards.
            outcomes = {"TP": 0, "SL": 0, "SQUARE_OFF": 0, "OTHER": 0}
            for t in self._closed:
                outcomes[t["reason"] if t["reason"] in outcomes else "OTHER"] += 1
            with self._siglock:
                signals_log = list(self._signals)[:200]
            return {
                "config": {"capital_per_trade": self.cfg.capital_per_trade,
                           "sl_atr": self.cfg.sl_atr, "tp_atr": self.cfg.tp_atr,
                           "max_positions": self.cfg.max_positions,
                           "square_off": self.cfg.square_off.strftime("%H:%M"),
                           "trade_intraday": self.cfg.trade_intraday,
                           "trade_options": self.cfg.trade_options,
                           "option_sl_pct": self.cfg.option_sl_pct,
                           "option_tp_pct": self.cfg.option_tp_pct},
                "strategies": list(per.values()),
                "open_positions": open_list,
                "closed_trades": self._closed[-100:],
                "signals_log": signals_log,
                "outcomes": outcomes,
                "realised_pnl": total_realised,
                "open_count": len(self._open),
            }

    def _emit(self) -> None:
        if self._broadcast:
            try:
                self._broadcast({"type": "algo_update", "data": self.snapshot()})
            except Exception:
                pass
