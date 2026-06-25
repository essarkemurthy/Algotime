"""
signals/engine.py — orchestrates detection → dedup → logging → notification.

The host feeds freshly-closed bars to on_bar_close(symbol, bar). The engine:
  1. resets per-symbol state at the 09:15 day boundary,
  2. runs every detector on the latest bar,
  3. dedups (one signal per symbol/strategy/side/day),
  4. ALWAYS logs the detection (signals table if a store is given, plus logger),
  5. notifies via the dispatcher unless the kill-switch is off / dry-run.

Detection runs synchronously in whatever thread delivers the bar (the Breeze SDK
tick thread in app.py). The work is small numpy over a day's worth of bars and
the DataStore connection pool is thread-safe, so this is safe; the only handoff
to the event loop is the injected broadcast callable inside the dispatcher.
"""

import logging
from collections import deque
from datetime import date
from typing import Callable, Dict, List, Optional

from .config import SignalConfig
from .detectors import DETECTORS, Signal
from .notifier import NotificationDispatcher, format_message, to_payload
from .session import SymbolSession

log = logging.getLogger("signals")


class SignalEngine:
    def __init__(self, cfg: SignalConfig, store=None,
                 broadcast_fn: Optional[Callable[[dict], None]] = None) -> None:
        self.cfg = cfg
        self.store = store
        self.notifier = NotificationDispatcher(cfg, broadcast_fn)
        self._sessions: Dict[str, SymbolSession] = {}
        self._fired: set = set()                     # dedup keys (trade_date, sym, strat, dir)
        self.recent: deque = deque(maxlen=200)       # recent payloads for the API/UI

    # ── runtime kill-switch ───────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> None:
        self.cfg.enabled = enabled
        log.info("Signal notifications %s.", "ENABLED" if enabled else "DISABLED (kill-switch)")

    # ── seeding (optional) ────────────────────────────────────────────────────

    def seed_session(self, symbol: str, bars: List[dict], trade_date: date) -> None:
        """Pre-fill a symbol's session from historical bars (e.g. on mid-day start).

        Bars are added without running detection so that, once live bars arrive,
        indicators reflect the full session from 09:15.
        """
        sess = self._session_for(symbol, trade_date)
        for b in bars:
            sess.add_bar(b)
        log.info("Seeded %s with %d historical bars for %s.", symbol, len(bars), trade_date)

    # ── main entry point ──────────────────────────────────────────────────────

    def on_bar_close(self, symbol: str, bar: dict) -> List[Signal]:
        """Process one freshly-closed bar. Returns the signals fired on it."""
        td = bar["ts"].date()
        sess = self._session_for(symbol, td)
        sess.add_bar(bar)

        fired: List[Signal] = []
        for detect in DETECTORS:
            try:
                sig = detect(sess)
            except Exception as exc:
                log.error("Detector %s failed for %s: %s", detect.__name__, symbol, exc)
                continue
            if sig is None or sig.dedup_key in self._fired:
                continue
            self._fired.add(sig.dedup_key)
            self._handle(sig)
            fired.append(sig)
        return fired

    # ── internals ─────────────────────────────────────────────────────────────

    def _session_for(self, symbol: str, td: date) -> SymbolSession:
        sess = self._sessions.get(symbol)
        if sess is None:
            sess = SymbolSession(symbol=symbol, cfg=self.cfg, trade_date=td)
            self._sessions[symbol] = sess
        elif sess.trade_date != td:
            sess.reset(td)            # 09:15 day boundary → fresh session
        return sess

    def _handle(self, sig: Signal) -> None:
        # 1. Always log the detection, regardless of notification state (safeguard).
        log.info("SIGNAL %s", format_message(sig))
        notified = False
        try:
            notified = self.notifier.dispatch(sig)
        except Exception as exc:
            log.error("Notification dispatch failed: %s", exc)

        # 2. Always persist to the signals table if a store is configured.
        if self.store is not None:
            try:
                self.store.insert_signal({
                    "ts":            sig.ts,
                    "trade_date":    sig.trade_date,
                    "symbol":        sig.symbol,
                    "strategy":      sig.strategy,
                    "direction":     sig.direction,
                    "trigger_price": sig.trigger_price,
                    "vwap":          sig.vwap,
                    "rsi":           None if sig.rsi != sig.rsi else sig.rsi,
                    "vol_ratio":     sig.vol_ratio,
                    "atr":           None if sig.atr != sig.atr else sig.atr,
                    "notified":      notified,
                })
            except Exception as exc:
                log.warning("Signal DB log failed: %s", exc)

        self.recent.appendleft(to_payload(sig))
