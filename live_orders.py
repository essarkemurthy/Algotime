"""
live_orders.py - mirror the options paper engine's entries/exits onto the real
broker account, sized from the funds actually available, behind two independent
safety gates.

The paper engine (paper_algo.AlgoPaperTrader) stays the decision maker: it
resolves the ATM contract, sizes the paper position, and manages SL/TP/square-
off. This bridge only *follows* it on the broker, so the paper book is always
the superset and the live book can be reconciled against it.

Gates (both must hold before a single real order goes out):
  1. LIVE_ORDERS_ENABLED=1 in the environment (.env) - the operator's standing
     consent, set by hand.
  2. Armed for the day through POST /api/live/arm with the exact confirmation
     phrase. Arming is NOT persisted: every restart and every new day starts
     disarmed. Arming starts in DRY-RUN (orders are logged, not sent) unless
     `dry_run` is explicitly false.

Position sizing (per entry, from the broker's get_funds, refreshed ≤ 60 s old):
  capital        = F&O allocation + unallocated bank balance (capped by
                   LIVE_CAPITAL when set)
  lots = min( max_lots,
              risk budget      / risk per lot       (risk_pct % of capital at the
                                                     paper stop, sl_frac of premium)
              entry exposure   / premium per lot    (exposure_pct % of capital)
              remaining total exposure / premium per lot (total_exposure_pct %)
              spendable cash   / premium per lot    (cash less cash_buffer_pct)
              max_premium_inr  / premium per lot )
  0 lots → the entry is skipped and the reason says what one lot would need.
Day-level circuit breakers: daily loss cap = min(absolute cap, daily_loss_pct %
of capital at arming) disarms; max_trades_per_day; max_consec_losses disarms;
max_open concurrent positions. A kill switch sells every live position at
market and disarms. The square-off is the paper engine's own.

Every real or dry-run order, and every skipped entry, is journaled to the
`live_orders` table with the sizing arithmetic in `reason`.
"""

from __future__ import annotations

import logging
import math
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


def _inr(x: float) -> str:
    return f"{x:,.0f}"


@dataclass
class LiveConfig:
    lots: int = 0                             # 0 = size from funds; >0 = fixed lots (still cash-checked)
    max_lots: int = 5                         # hard ceiling per entry
    max_open: int = 1
    risk_pct: float = 2.0                     # % of capital at risk per trade (premium x sl_frac)
    sl_frac: float = 0.30                     # the paper engine's option stop, as a fraction of premium
    exposure_pct: float = 25.0                # max premium of ONE entry, % of capital
    total_exposure_pct: float = 50.0          # max premium of all open live positions, % of capital
    cash_buffer_pct: float = 5.0              # never spend the last x% (brokerage, taxes, slippage)
    daily_loss_cap_inr: float = 3000.0        # absolute ceiling on the day's realised loss
    daily_loss_pct: float = 3.0               # ... and relative: % of capital at arming (lower wins)
    max_premium_inr: float = 20000.0          # absolute ceiling on premium x qty for one entry
    max_trades_per_day: int = 3
    max_consec_losses: int = 2                # disarm after this many losing live exits in a row
    capital_override_inr: float = 0.0         # >0: never size against more than this much capital
    underlyings: frozenset = frozenset({"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"})
    lot_size: Dict[str, int] = field(default_factory=lambda: {
        "NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 120, "SENSEX": 20})
    fill_poll_sec: float = 1.0
    fill_poll_tries: int = 8
    funds_ttl_sec: float = 60.0


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
    lots: int = 1


@dataclass
class Sizing:
    lots: int
    qty: int
    reason: str                   # arithmetic, journaled with the entry or the skip
    capital: float


class LiveOrderBridge:
    def __init__(self, api_getter: Callable[[], object], cfg: Optional[LiveConfig] = None,
                 store=None, broadcast: Optional[Callable[[dict], None]] = None,
                 code_of: Optional[Callable[[str], str]] = None,
                 funds_getter: Optional[Callable[[], Optional[dict]]] = None) -> None:
        self._api_getter = api_getter
        self._funds_getter = funds_getter
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
        self.trades_today = 0                    # live entries placed today (dry or real)
        self.consec_losses = 0
        self.capital_at_arm = 0.0
        self.last_sizing: Optional[str] = None
        self._funds: Optional[dict] = None
        self._funds_at = 0.0
        self._funds_err: Optional[str] = None
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
        cap = self.capital(force=True)
        with self._lock:
            self.armed = True
            self.dry_run = bool(dry_run)
            self.armed_on = date.today()
            self.armed_at = datetime.now()
            self.killed = False
            self.disarm_reason = None
            self.capital_at_arm = cap
        log.warning("LIVE ORDERS ARMED (%s) capital=%s risk/trade=%.1f%% max_lots=%d max_open=%d loss_cap=%s",
                    "DRY-RUN" if self.dry_run else "REAL MONEY", _inr(cap), self.cfg.risk_pct,
                    self.cfg.max_lots, self.cfg.max_open, _inr(self.loss_cap()))
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
            self.trades_today = 0
            self.consec_losses = 0
            self.last_sizing = None
            if self.armed:
                self.armed = False
                self.disarm_reason = "new day: re-arm required"

    @property
    def active(self) -> bool:
        self._roll_day()
        return self.armed and self.armed_on == date.today() and not self.killed

    # ── funds and sizing ─────────────────────────────────────────────────────

    def refresh_funds(self, force: bool = False) -> Optional[dict]:
        """Broker funds, cached for funds_ttl_sec. Never raises."""
        if self._funds_getter is None:
            return self._funds
        if not force and self._funds is not None and (time.time() - self._funds_at) < self.cfg.funds_ttl_sec:
            return self._funds
        try:
            f = self._funds_getter()
            if f:
                self._funds, self._funds_at, self._funds_err = dict(f), time.time(), None
            else:
                self._funds_err = "broker returned no funds"
        except Exception as exc:
            self._funds_err = str(exc)
            log.warning("live funds refresh failed: %s", exc)
        return self._funds

    def capital(self, force: bool = False) -> float:
        """Capital the sizer works against: F&O allocation + unallocated bank
        balance, capped by capital_override_inr when set. 0 when unknown."""
        f = self.refresh_funds(force) or {}
        cap = float(f.get("allocated_fno") or 0) + float(f.get("unallocated") or 0)
        if self.cfg.capital_override_inr > 0:
            cap = min(cap, self.cfg.capital_override_inr)
        return max(cap, 0.0)

    def loss_cap(self) -> float:
        """Effective daily loss cap: the lower of the absolute and the relative one."""
        rel = self.capital_at_arm * self.cfg.daily_loss_pct / 100.0 if self.capital_at_arm > 0 else 0.0
        caps = [abs(self.cfg.daily_loss_cap_inr)] + ([rel] if rel > 0 else [])
        return min(caps)

    def _open_premium(self, dry_only: bool = False) -> float:
        with self._lock:
            return sum(p.entry * p.qty for p in self.open.values() if (p.dry_run or not dry_only))

    def size(self, stock: str, premium: float) -> Sizing:
        """How many lots of `stock` to buy at `premium`, and why. Pure arithmetic
        over the cached funds; the caller decides whether to act on it."""
        c = self.cfg
        lot = c.lot_size.get(stock, 0)
        cap = self.capital()
        if lot <= 0:
            return Sizing(0, 0, "unknown lot size", cap)
        if premium <= 0:
            return Sizing(0, 0, "no premium", cap)
        if cap <= 0:
            return Sizing(0, 0, "capital unknown: broker funds unavailable" + (f" ({self._funds_err})" if self._funds_err else ""), cap)
        prem_lot = premium * lot
        risk_lot = prem_lot * c.sl_frac
        risk_budget = cap * c.risk_pct / 100.0
        entry_budget = cap * c.exposure_pct / 100.0
        open_prem = self._open_premium()
        room = cap * c.total_exposure_pct / 100.0 - open_prem
        # In real mode the broker balance already reflects premium paid for open
        # positions; dry-run positions never debited anything, so subtract them.
        cash = cap * (1 - c.cash_buffer_pct / 100.0) - self._open_premium(dry_only=True)
        limits = {
            f"risk {c.risk_pct:g}% = {_inr(risk_budget)} / {_inr(risk_lot)} per lot": risk_budget / risk_lot,
            f"entry {c.exposure_pct:g}% = {_inr(entry_budget)}": entry_budget / prem_lot,
            f"total {c.total_exposure_pct:g}% room {_inr(room)}": room / prem_lot,
            f"cash {_inr(cash)}": cash / prem_lot,
            f"premium cap {_inr(c.max_premium_inr)}": c.max_premium_inr / prem_lot,
            f"max_lots {c.max_lots}": float(c.max_lots),
        }
        if c.lots > 0:
            limits = {k: v for k, v in limits.items() if k.startswith(("cash", "premium cap"))}
            limits[f"fixed LIVE_LOTS {c.lots}"] = float(c.lots)
        binding = min(limits, key=limits.get)
        n = max(0, int(math.floor(limits[binding] + 1e-9)))
        head = f"capital {_inr(cap)} | premium/lot {_inr(prem_lot)} (x{lot}) | risk/lot {_inr(risk_lot)}"
        if n == 0:
            need = max(risk_lot * 100.0 / c.risk_pct if c.lots <= 0 else 0.0,
                       prem_lot * 100.0 / c.exposure_pct if c.lots <= 0 else 0.0,
                       prem_lot / (1 - c.cash_buffer_pct / 100.0))
            return Sizing(0, 0, f"0 lots - binding: {binding}; one lot needs capital ~ {_inr(need)} | {head}", cap)
        return Sizing(n, n * lot, f"{n} lot{'s' if n > 1 else ''} - binding: {binding} | {head}", cap)

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
        self.last_sizing = why
        self._journal(symbol=pos.symbol, instrument=pos.instrument, action="skip", qty=0,
                      order_id=None, status="SKIPPED", price=None, paper_price=pos.entry,
                      reason=why, pnl=None)
        self._emit()

    def _entry(self, pos, paper_fill: float) -> None:
        if not self.active or getattr(pos, "product", "") != "options":
            return
        if pos.stock not in self.cfg.underlyings:
            return self._skip(pos, "underlying not allowed")
        if self.realised_pnl <= -self.loss_cap():
            self.disarm("daily loss cap")
            return self._skip(pos, "daily loss cap reached")
        if self.trades_today >= self.cfg.max_trades_per_day:
            return self._skip(pos, f"max_trades_per_day {self.cfg.max_trades_per_day} reached")
        with self._lock:
            if pos.symbol in self.open:
                return self._skip(pos, "already live")
            if len(self.open) >= self.cfg.max_open:
                return self._skip(pos, f"max_open {self.cfg.max_open} reached")
        sz = self.size(pos.stock, paper_fill)
        if sz.lots <= 0:
            return self._skip(pos, sz.reason)
        qty = sz.qty
        api = self._api_getter()
        if api is None and not self.dry_run:
            return self._skip(pos, "broker offline")
        order_id, fill, status = self._place(api, pos, "buy", qty, paper_fill)
        if order_id is None:
            return self._skip(pos, f"order rejected: {status} | {sz.reason}")
        lp = LivePos(symbol=pos.symbol, instrument=pos.instrument or pos.symbol,
                     stock=self._code_of(pos.stock), exchange=pos.exchange, right=pos.right,
                     strike=int(pos.strike), expiry=str(pos.expiry), qty=qty, order_id=order_id,
                     entry=fill or paper_fill, paper_entry=paper_fill, opened_at=datetime.now(),
                     dry_run=self.dry_run, lots=sz.lots)
        with self._lock:
            self.open[pos.symbol] = lp
            self.trades_today += 1
            self.last_sizing = sz.reason
        self._journal(symbol=pos.symbol, instrument=lp.instrument, action="buy", qty=qty,
                      order_id=order_id, status=status, price=lp.entry, paper_price=paper_fill,
                      reason="entry: " + sz.reason, pnl=None)
        log.warning("LIVE %sBUY %s x%d (%s) @ %.2f (paper %.2f) order %s", "DRY-RUN " if self.dry_run else "",
                    lp.instrument, qty, sz.reason, lp.entry, paper_fill, order_id)
        if not self.dry_run:
            self._funds_at = 0.0          # premium was debited: re-read funds before the next sizing
        self._emit()

    def _exit(self, symbol: str, paper_exit: Optional[float], reason: str) -> None:
        with self._lock:
            lp = self.open.get(symbol)
        if lp is None:
            return
        api = self._api_getter()
        order_id, fill, status = self._place(api, lp, "sell", lp.qty, paper_exit or lp.entry, live=lp)
        if order_id is None:
            log.error("LIVE SELL REJECTED for %s (%s) - position stays open, retry on next exit/kill",
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
            self.consec_losses = self.consec_losses + 1 if pnl < 0 else 0
        self._journal(symbol=symbol, instrument=lp.instrument, action="sell", qty=lp.qty,
                      order_id=order_id, status=status, price=exit_px, paper_price=paper_exit,
                      reason=reason, pnl=round(pnl, 2))
        log.warning("LIVE %sSELL %s x%d @ %.2f  %s  P&L %.2f (day %.2f)", "DRY-RUN " if lp.dry_run else "",
                    lp.instrument, lp.qty, exit_px, reason, pnl, self.realised_pnl)
        if not lp.dry_run:
            self._funds_at = 0.0
        if self.armed and self.realised_pnl <= -self.loss_cap():
            self.disarm("daily loss cap")
        elif self.armed and self.cfg.max_consec_losses > 0 and self.consec_losses >= self.cfg.max_consec_losses:
            self.disarm(f"{self.consec_losses} consecutive losses")
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
        c = self.cfg
        funds = self._funds or {}
        with self._lock:
            open_rows = [{"symbol": p.symbol, "instrument": p.instrument, "qty": p.qty, "lots": p.lots,
                          "entry": p.entry, "paper_entry": p.paper_entry, "order_id": p.order_id,
                          "opened_at": p.opened_at.strftime("%H:%M:%S"), "dry_run": p.dry_run}
                         for p in self.open.values()]
            cap = float(funds.get("allocated_fno") or 0) + float(funds.get("unallocated") or 0)
            if c.capital_override_inr > 0:
                cap = min(cap, c.capital_override_inr)
            return {
                "env_enabled": self.env_enabled, "armed": self.armed, "dry_run": self.dry_run,
                "active": self.armed and self.armed_on == date.today() and not self.killed,
                "killed": self.killed, "disarm_reason": self.disarm_reason,
                "armed_at": self.armed_at.strftime("%H:%M:%S") if self.armed_at else None,
                "lots": c.lots, "max_lots": c.max_lots, "max_open": c.max_open,
                "capital": round(cap, 2), "capital_at_arm": round(self.capital_at_arm, 2),
                "funds": funds, "funds_at": datetime.fromtimestamp(self._funds_at).strftime("%H:%M:%S") if self._funds_at else None,
                "funds_error": self._funds_err,
                "sizing": {"risk_pct": c.risk_pct, "sl_frac": c.sl_frac, "exposure_pct": c.exposure_pct,
                           "total_exposure_pct": c.total_exposure_pct, "cash_buffer_pct": c.cash_buffer_pct,
                           "daily_loss_pct": c.daily_loss_pct, "max_trades_per_day": c.max_trades_per_day,
                           "max_consec_losses": c.max_consec_losses, "capital_override_inr": c.capital_override_inr},
                "risk_budget": round(cap * c.risk_pct / 100.0, 2),
                "daily_loss_cap_inr": round(self.loss_cap(), 2),
                "max_premium_inr": c.max_premium_inr,
                "trades_today": self.trades_today, "consec_losses": self.consec_losses,
                "last_sizing": self.last_sizing,
                "underlyings": sorted(c.underlyings),
                "realised_pnl": round(self.realised_pnl, 2),
                "open": open_rows, "orders": self.orders[-50:], "confirm_phrase": CONFIRM_PHRASE,
            }

    def _emit(self) -> None:
        if self._broadcast is not None:
            try:
                self._broadcast({"type": "live_update", "data": self.state()})
            except Exception:
                pass
