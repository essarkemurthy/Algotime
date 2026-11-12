"""
live_orders.py — mirror the options paper engine's entries/exits onto the real
broker account, one lot at a time, behind two independent safety gates.

The paper engine (paper_algo.AlgoPaperTrader) stays the decision maker: it
resolves the ATM contract, sizes the paper position, and manages SL/TP/square-
off. This bridge only *follows* it on the broker with `lots` real lots, so the
paper book is always the superset and the live book can be reconciled against it.

Gates (both must hold before a single real order goes out):
  1. LIVE_ORDERS_ENABLED=1 in the environment (.env) — the operator's standing
     consent, set by hand.
  2. Armed for the day through POST /api/live/arm with the exact confirmation
     phrase. Arming is NOT persisted: every restart and every new day starts
     disarmed. Arming starts in DRY-RUN (orders are logged, not sent) unless
     `dry_run` is explicitly false.
Limits: max open live positions, daily realised-loss cap (disarms when hit),
max premium per entry, allowed underlyings. A kill switch sells every live
position at market and disarms. The square-off is the paper engine's own.

Every real or dry-run order is journaled to the `live_orders` table.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

log = logging.getLogger("live")

CONFIRM_PHRASE = "I APPROVE LIVE ORDERS"
ENV_FLAG = "LIVE_ORDERS_ENABLED"


def _env_on() -> bool:
    return os.getenv(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _breeze_dt(d: date) -> str:
    return datetime(d.year, d.month, d.day, 6).isoformat(timespec="milliseconds") + "Z"


@dataclass
class LiveConfig:
    lots: int = 1
    max_open: int = 1
    daily_loss_cap_inr: float = 3000.0
    max_premium_inr: float = 20000.0          # premium x qty for one entry
    underlyings: frozenset = frozenset({"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"})
    lot_size: Dict[str, int] = field(default_factory=lambda: {
        "NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 120, "SENSEX": 20})
    fill_poll_sec: float = 1.0
    fill_poll_tries: int = 8


@dataclass
class LivePos:
    symbol: str                   # paper option key, e.g. NIFTY_CE_25300_2026-11-17
    instrument: str
    stock: str                    # Breeze code of the underlying (NIFTY, CNXBAN, BSESEN, ...)
    exchange: str                 # NFO | BFO
    right: str                    # CE | PE
    strike: int
    expiry: str                   # YYYY-MM-DD
    qty: int
    order_id: str
    entry: float                  # broker average fill (or paper price in dry-run)
    paper_entry: float
    opened_at: datetime
    dry_run: bool


class LiveOrderBridge:
    def __init__(self, api_getter: Callable[[], object], cfg: Optional[LiveConfig] = None,
                 store=None, broadcast: Optional[Callable[[dict], None]] = None,
                 code_of: Optional[Callable[[str], str]] = None) -> None:
        self._api_getter = api_getter
        self.cfg = cfg or LiveConfig()
        self.store = store
        self._broadcast = broadcast
        self._code_of = code_of or (lambda s: s)
        self._lock = threading.Lock()
        self._order_lock = threading.RLock()
        self.armed = False
        self.dry_run = True
        self.armed_on: Optional[date] = None
        self.armed_at: Optional[datetime] = None
        self.killed = False
        self.disarm_reason: Optional[str] = None
        self.open: Dict[str, LivePos] = {}
        self.orders: List[dict] = []             # today's journal rows (newest last)
        self.realised_pnl = 0.0
        self.day = date.today()

    # ── arming ───────────────────────────────────────────────────────────────

    @property
    def env_enabled(self) -> bool:
        return _env_on()

    def arm(self, confirm: str, dry_run: bool = True) -> dict:
        if not self.env_enabled:
            return {"ok": False, "error": f"{ENV_FLAG} is not set in the environment"}
        if (confirm or "").strip() != CONFIRM_PHRASE:
            return {"ok": False, "error": "confirmation phrase does not match"}
        self._roll_day()
        with self._lock:
            self.armed = True
            self.dry_run = bool(dry_run)
            self.armed_on = date.today()
            self.armed_at = datetime.now()
            self.killed = False
            self.disarm_reason = None
        log.warning("LIVE ORDERS ARMED (%s) lots=%d max_open=%d loss_cap=%.0f",
                    "DRY-RUN" if self.dry_run else "REAL MONEY", self.cfg.lots,
                    self.cfg.max_open, self.cfg.daily_loss_cap_inr)
        self._emit()
        return {"ok": True, **self.state()}

    def disarm(self, reason: str = "manual") -> dict:
        with self._lock:
            self.armed = False
            self.disarm_reason = reason
        log.warning("LIVE ORDERS DISARMED (%s)", reason)
        self._emit()
        return self.state()

    def kill(self) -> dict:
        """Sell every live position at market, then disarm. Idempotent."""
        self.killed = True
        self.flatten_all("KILL")
        return self.disarm("kill switch")

    def _roll_day(self) -> None:
        if date.today() != self.day:
            self.day = date.today()
            self.orders.clear()
            self.realised_pnl = 0.0
            if self.armed:
                self.armed = False
                self.disarm_reason = "new day: re-arm required"

    @property
    def active(self) -> bool:
        self._roll_day()
        return self.armed and self.armed_on == date.today() and not self.killed

    # ── hooks called by the paper engine ─────────────────────────────────────

    # The paper engine calls these from the event loop (entries) and the SDK tick
    # thread (exits). A real order takes seconds (placement + fill poll), so the
    # work runs on a daemon thread, serialised by _order_lock so an exit can never
    # overtake its own entry. `sync=True` (tests) runs inline.
    sync = False

    def _run(self, fn, *args) -> None:
        def _job():
            with self._order_lock:
                try:
                    fn(*args)
                except Exception as exc:
                    log.error("live order job failed (%s): %s", fn.__name__, exc)
        if self.sync:
            _job()
        else:
            threading.Thread(target=_job, name="live-order", daemon=True).start()

    def on_paper_entry(self, pos, paper_fill: float) -> None:
        """pos: paper_algo._OpenPos (product='options'). Never raises."""
        if self.active and getattr(pos, "product", "") == "options":
            self._run(self._entry, pos, float(paper_fill))

    def on_paper_exit(self, pos, paper_exit: float, reason: str) -> None:
        if pos.symbol in self.open:
            self._run(self._exit, pos.symbol, float(paper_exit) if paper_exit else None, reason)

    def flatten_all(self, reason: str) -> None:
        for sym in list(self.open):
            self._run(self._exit, sym, None, reason)

    # ── order placement ──────────────────────────────────────────────────────

    def _skip(self, pos, why: str) -> None:
        log.info("live entry skipped %s: %s", pos.symbol, why)
        self._journal(symbol=pos.symbol, instrument=pos.instrument, action="skip", qty=0,
                      order_id=None, status="SKIPPED", price=None, paper_price=pos.entry,
                      reason=why, pnl=None)
        self._emit()

    def _entry(self, pos, paper_fill: float) -> None:
        if not self.active or getattr(pos, "product", "") != "options":
            return
        if pos.stock not in self.cfg.underlyings:
            return self._skip(pos, "underlying not allowed")
        if self.realised_pnl <= -abs(self.cfg.daily_loss_cap_inr):
            self.disarm("daily loss cap")
            return self._skip(pos, "daily loss cap reached")
        with self._lock:
            if pos.symbol in self.open:
                return self._skip(pos, "already live")
            if len(self.open) >= self.cfg.max_open:
                return self._skip(pos, f"max_open {self.cfg.max_open} reached")
        lot = self.cfg.lot_size.get(pos.stock, 0)
        if lot <= 0:
            return self._skip(pos, "unknown lot size")
        qty = lot * self.cfg.lots
        if paper_fill * qty > self.cfg.max_premium_inr:
            return self._skip(pos, f"premium {paper_fill * qty:.0f} > cap {self.cfg.max_premium_inr:.0f}")
        api = self._api_getter()
        if api is None and not self.dry_run:
            return self._skip(pos, "broker offline")
        order_id, fill, status = self._place(api, pos, "buy", qty, paper_fill)
        if order_id is None:
            return self._skip(pos, f"order rejected: {status}")
        lp = LivePos(symbol=pos.symbol, instrument=pos.instrument or pos.symbol,
                     stock=self._code_of(pos.stock), exchange=pos.exchange, right=pos.right,
                     strike=int(pos.strike), expiry=str(pos.expiry), qty=qty, order_id=order_id,
                     entry=fill or paper_fill, paper_entry=paper_fill, opened_at=datetime.now(),
                     dry_run=self.dry_run)
        with self._lock:
            self.open[pos.symbol] = lp
        self._journal(symbol=pos.symbol, instrument=lp.instrument, action="buy", qty=qty,
                      order_id=order_id, status=status, price=lp.entry, paper_price=paper_fill,
                      reason="entry", pnl=None)
        log.warning("LIVE %sBUY %s x%d @ %.2f (paper %.2f) order %s", "DRY-RUN " if self.dry_run else "",
                    lp.instrument, qty, lp.entry, paper_fill, order_id)
        self._emit()

    def _exit(self, symbol: str, paper_exit: Optional[float], reason: str) -> None:
        with self._lock:
            lp = self.open.get(symbol)
        if lp is None:
            return
        api = self._api_getter()
        order_id, fill, status = self._place(api, lp, "sell", lp.qty, paper_exit or lp.entry, live=lp)
        if order_id is None:
            log.error("LIVE SELL REJECTED for %s (%s) — position stays open, retry on next exit/kill",
                      lp.instrument, status)
            self._journal(symbol=symbol, instrument=lp.instrument, action="sell", qty=lp.qty,
                          order_id=None, status=f"REJECTED {status}", price=None,
                          paper_price=paper_exit, reason=reason, pnl=None)
            self._emit()
            return
        exit_px = fill or paper_exit or lp.entry
        pnl = (exit_px - lp.entry) * lp.qty
        with self._lock:
            self.open.pop(symbol, None)
            self.realised_pnl += pnl
        self._journal(symbol=symbol, instrument=lp.instrument, action="sell", qty=lp.qty,
                      order_id=order_id, status=status, price=exit_px, paper_price=paper_exit,
                      reason=reason, pnl=round(pnl, 2))
        log.warning("LIVE %sSELL %s x%d @ %.2f  %s  P&L %.2f (day %.2f)", "DRY-RUN " if lp.dry_run else "",
                    lp.instrument, lp.qty, exit_px, reason, pnl, self.realised_pnl)
        if self.realised_pnl <= -abs(self.cfg.daily_loss_cap_inr) and self.armed:
            self.disarm("daily loss cap")
        self._emit()

    def _place(self, api, pos, action: str, qty: int, ref_price: float, live: Optional[LivePos] = None):
        """Returns (order_id, fill_price, status). Dry-run fabricates an id."""
        if self.dry_run:
            return f"DRY-{datetime.now():%H%M%S}-{action}", float(ref_price), "DRY-RUN"
        stock = live.stock if live else self._code_of(pos.stock)
        exchange = live.exchange if live else pos.exchange
        right = (live.right if live else pos.right)
        strike = live.strike if live else int(pos.strike)
        expiry = date.fromisoformat(str(live.expiry if live else pos.expiry))
        resp = api.place_order(
            stock_code=stock, exchange_code=exchange, product="options", action=action,
            order_type="market", stoploss="0", quantity=str(qty), price="0", validity="day",
            validity_date=_breeze_dt(date.today()), disclosed_quantity="0",
            expiry_date=_breeze_dt(expiry), right="call" if right == "CE" else "put",
            strike_price=str(strike))
        if not isinstance(resp, dict) or resp.get("Status") != 200 or not resp.get("Success"):
            return None, None, str((resp or {}).get("Error") if isinstance(resp, dict) else resp)
        order_id = str(resp["Success"].get("order_id") or "")
        fill, status = self._await_fill(api, exchange, order_id)
        return order_id, fill, status

    def _await_fill(self, api, exchange: str, order_id: str):
        """Poll order detail briefly for the average fill price. Market orders on
        index options normally fill within a second."""
        status, fill = "PLACED", None
        for _ in range(self.cfg.fill_poll_tries):
            time.sleep(self.cfg.fill_poll_sec)
            try:
                resp = api.get_order_detail(exchange_code=exchange, order_id=order_id)
            except Exception as exc:
                log.debug("order detail %s: %s", order_id, exc)
                continue
            rows = resp.get("Success") if isinstance(resp, dict) else None
            if not rows:
                continue
            row = rows[0] if isinstance(rows, list) else rows
            status = str(row.get("status") or status)
            try:
                px = float(row.get("average_price") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                fill = px
            if status.lower() in ("executed", "complete", "filled") or (fill and status.lower() != "rejected"):
                break
            if status.lower() in ("rejected", "cancelled"):
                break
        return fill, status

    # ── journal / state ──────────────────────────────────────────────────────

    def _journal(self, **row) -> None:
        row = {"ts": datetime.now(), "dry_run": self.dry_run, **row}
        self.orders.append({**row, "ts": row["ts"].strftime("%H:%M:%S")})
        if self.store is not None:
            try:
                self.store.insert_live_order(row)
            except Exception as exc:
                log.warning("live journal write failed: %s", exc)

    def state(self) -> dict:
        self._roll_day()
        with self._lock:
            open_rows = [{"symbol": p.symbol, "instrument": p.instrument, "qty": p.qty,
                          "entry": p.entry, "paper_entry": p.paper_entry, "order_id": p.order_id,
                          "opened_at": p.opened_at.strftime("%H:%M:%S"), "dry_run": p.dry_run}
                         for p in self.open.values()]
            return {
                "env_enabled": self.env_enabled, "armed": self.armed, "dry_run": self.dry_run,
                "active": self.armed and self.armed_on == date.today() and not self.killed,
                "killed": self.killed, "disarm_reason": self.disarm_reason,
                "armed_at": self.armed_at.strftime("%H:%M:%S") if self.armed_at else None,
                "lots": self.cfg.lots, "max_open": self.cfg.max_open,
                "daily_loss_cap_inr": self.cfg.daily_loss_cap_inr,
                "max_premium_inr": self.cfg.max_premium_inr,
                "underlyings": sorted(self.cfg.underlyings),
                "realised_pnl": round(self.realised_pnl, 2),
                "open": open_rows, "orders": self.orders[-50:], "confirm_phrase": CONFIRM_PHRASE,
            }

    def _emit(self) -> None:
        if self._broadcast is not None:
            try:
                self._broadcast({"type": "live_update", "data": self.state()})
            except Exception:
                pass
