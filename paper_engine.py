"""
paper_engine.py — In-memory paper trading engine.

Orders fill immediately at live LTP (market) or at the specified limit price.
No real orders are sent to Breeze.

Professional features (added):
  - Fixed-fractional position sizing (risk per trade / risk per share)
  - 3-tier exit: T1 (partial), T2 (partial), trailing remainder
  - Auto-exit monitor via check_auto_exits() — called by background task
  - Daily loss cap enforcement with halted flag
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as _time, timezone, timedelta
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("paper")

_IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(tz=_IST)


@dataclass
class PaperOrder:
    id:         str
    time:       str
    stock:      str
    exchange:   str
    product:    str           # cash | options
    right:      Optional[str] # CE | PE
    strike:     Optional[int]
    expiry:     Optional[str]
    symbol:     str
    action:     str           # buy | sell
    qty:        int
    fill_price: float
    order_type: str           # market | limit
    status:     str = "filled"
    tag:        str = ""      # strategy label / exit reason


@dataclass
class PaperPosition:
    id:          str
    stock:       str
    exchange:    str
    product:     str
    right:       Optional[str]
    strike:      Optional[int]
    expiry:      Optional[str]
    symbol:      str
    direction:   str    # buy | sell
    qty:         int
    avg_price:   float
    is_open:     bool = True
    realised_pnl: float = 0.0
    opened_at:   str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    closed_at:   Optional[str] = None
    tag:         str = ""     # strategy label

    # ── SL / 3-tier exit levels (set via set_levels()) ──────────────────────
    sl_price:     Optional[float] = None
    t1_price:     Optional[float] = None   # first target — partial exit
    t2_price:     Optional[float] = None   # second target — partial exit
    t1_qty:       int = 0                  # shares to sell at T1
    t2_qty:       int = 0                  # shares to sell at T2
    trail_pct:    float = 0.004            # trailing % for remainder after T2
    t1_hit:       bool = False
    t2_hit:       bool = False
    highest_seen: Optional[float] = None   # for buy trailing
    lowest_seen:  Optional[float] = None   # for sell trailing


def _symbol_key(stock: str, product: str, right: Optional[str],
                strike: Optional[int], expiry: Optional[str]) -> str:
    if product == "options" and right and strike:
        return f"{stock}_{right}_{strike}_{expiry or ''}"
    return stock


class PaperTrader:
    """Simulated order book — fills instantly at LTP, tracks P&L mark-to-market."""

    def __init__(self, starting_capital: float = 1_000_000.0) -> None:
        self.starting_capital = starting_capital
        self.cash             = starting_capital
        self._orders:         List[PaperOrder]    = []
        self._positions:      List[PaperPosition] = []
        self._strategy_trades: List[dict]         = []
        self._seq = 0

        # ── Daily loss cap ───────────────────────────────────────────────────
        self.daily_loss_cap:    float = 8_000.0   # ₹8,000 total daily cap
        self.per_slot_loss_cap: float = 3_000.0   # ₹3,000 per strategy slot
        self.halted:            bool  = False

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        stock:      str,
        exchange:   str,
        product:    str,
        action:     str,
        qty:        int,
        order_type: str,
        price:      float,
        ltp_cache:  Dict[str, float],
        right:      Optional[str] = None,
        strike:     Optional[int] = None,
        expiry:     Optional[str] = None,
        tag:        str = "",
    ) -> PaperOrder:
        """Fill a paper order. Returns the filled PaperOrder."""
        symbol = _symbol_key(stock, product, right, strike, expiry)

        if order_type == "limit" and price > 0:
            fill_price = price
        else:
            fill_price = ltp_cache.get(symbol) or ltp_cache.get(stock) or price
            if fill_price <= 0:
                raise ValueError(
                    f"No live price for {symbol}. "
                    "Enter a limit price or connect and let LTP cache warm up."
                )

        cost = fill_price * qty
        if action == "buy":
            if cost > self.cash:
                raise ValueError(
                    f"Insufficient paper cash: need ₹{cost:,.0f}, "
                    f"available ₹{self.cash:,.0f}."
                )
            self.cash -= cost
        else:
            self.cash += cost

        self._seq += 1
        order = PaperOrder(
            id=f"P{self._seq:04d}",
            time=datetime.now().strftime("%H:%M:%S"),
            stock=stock, exchange=exchange, product=product,
            right=right, strike=strike, expiry=expiry, symbol=symbol,
            action=action, qty=qty, fill_price=round(fill_price, 2),
            order_type=order_type, tag=tag,
        )
        self._orders.append(order)
        self._update_positions(order)
        log.info("Paper %s %s x%d @ Rs%.2f [%s] %s",
                 action.upper(), symbol, qty, fill_price, order.id, tag)
        return order

    def _update_positions(self, order: PaperOrder) -> None:
        same_dir = next(
            (p for p in self._positions
             if p.is_open and p.symbol == order.symbol and p.direction == order.action),
            None,
        )
        opp_dir = next(
            (p for p in self._positions
             if p.is_open and p.symbol == order.symbol and p.direction != order.action),
            None,
        )

        if opp_dir:
            close_qty = min(opp_dir.qty, order.qty)
            if order.action == "sell":
                realised = (order.fill_price - opp_dir.avg_price) * close_qty
            else:
                realised = (opp_dir.avg_price - order.fill_price) * close_qty
            opp_dir.realised_pnl += realised
            opp_dir.qty -= close_qty
            if opp_dir.qty <= 0:
                opp_dir.is_open = False
                opp_dir.closed_at = datetime.now().strftime("%H:%M:%S")
            remainder = order.qty - close_qty
            if remainder > 0:
                self._open_position(order, remainder)
        elif same_dir:
            total_qty = same_dir.qty + order.qty
            same_dir.avg_price = (
                (same_dir.avg_price * same_dir.qty + order.fill_price * order.qty)
                / total_qty
            )
            same_dir.qty = total_qty
        else:
            self._open_position(order, order.qty)

    def _open_position(self, order: PaperOrder, qty: int) -> None:
        pos = PaperPosition(
            id=f"PP{self._seq:04d}",
            stock=order.stock, exchange=order.exchange, product=order.product,
            right=order.right, strike=order.strike, expiry=order.expiry,
            symbol=order.symbol, direction=order.action,
            qty=qty, avg_price=order.fill_price,
            tag=order.tag,
        )
        self._positions.append(pos)

    # ── Exit ──────────────────────────────────────────────────────────────────

    def exit_position(self, pos_id: str, ltp_cache: Dict[str, float],
                      tag: str = "manual") -> PaperOrder:
        pos = next((p for p in self._positions if p.id == pos_id and p.is_open), None)
        if not pos:
            raise ValueError(f"Open paper position '{pos_id}' not found.")
        exit_action = "sell" if pos.direction == "buy" else "buy"
        return self.place_order(
            stock=pos.stock, exchange=pos.exchange, product=pos.product,
            action=exit_action, qty=pos.qty, order_type="market", price=0,
            ltp_cache=ltp_cache, right=pos.right,
            strike=pos.strike, expiry=pos.expiry, tag=tag,
        )

    def partial_exit(self, pos_id: str, qty: int,
                     ltp_cache: Dict[str, float], tag: str = "partial") -> PaperOrder:
        """Exit a specific quantity from an open position."""
        pos = next((p for p in self._positions if p.id == pos_id and p.is_open), None)
        if not pos:
            raise ValueError(f"Open paper position '{pos_id}' not found.")
        if qty >= pos.qty:
            return self.exit_position(pos_id, ltp_cache, tag=tag)
        exit_action = "sell" if pos.direction == "buy" else "buy"
        return self.place_order(
            stock=pos.stock, exchange=pos.exchange, product=pos.product,
            action=exit_action, qty=qty, order_type="market", price=0,
            ltp_cache=ltp_cache, right=pos.right,
            strike=pos.strike, expiry=pos.expiry, tag=tag,
        )

    def _partial_exit_at_price(self, pos: PaperPosition, qty: int,
                               ltp: float, tag: str = "") -> None:
        """Internal partial exit used by auto-monitor — bypasses ltp_cache lookup."""
        exit_action = "sell" if pos.direction == "buy" else "buy"
        if exit_action == "sell":
            realized = (ltp - pos.avg_price) * qty
            self.cash += ltp * qty
        else:
            realized = (pos.avg_price - ltp) * qty
            self.cash -= ltp * qty

        pos.realised_pnl += realized
        pos.qty -= qty

        self._seq += 1
        order = PaperOrder(
            id=f"P{self._seq:04d}",
            time=datetime.now().strftime("%H:%M:%S"),
            stock=pos.stock, exchange=pos.exchange, product=pos.product,
            right=pos.right, strike=pos.strike, expiry=pos.expiry, symbol=pos.symbol,
            action=exit_action, qty=qty, fill_price=round(ltp, 2),
            order_type="market", tag=tag,
        )
        self._orders.append(order)
        log.info("Auto %s %s x%d @ Rs%.2f [%s]",
                 exit_action.upper(), pos.symbol, qty, ltp, tag)

    # ── SL / T1 / T2 level management ────────────────────────────────────────

    def set_levels(
        self, pos_id: str,
        sl_price:  float,
        t1_price:  float,
        t2_price:  float,
        t1_qty:    int,
        t2_qty:    int,
        trail_pct: float = 0.004,
        tag:       str   = "",
    ) -> bool:
        pos = next((p for p in self._positions if p.id == pos_id and p.is_open), None)
        if not pos:
            return False
        pos.sl_price  = round(sl_price,  2)
        pos.t1_price  = round(t1_price,  2)
        pos.t2_price  = round(t2_price,  2)
        pos.t1_qty    = max(0, min(t1_qty, pos.qty - 1))
        pos.t2_qty    = max(0, min(t2_qty, pos.qty - pos.t1_qty - 1))
        pos.trail_pct = trail_pct
        pos.t1_hit    = False
        pos.t2_hit    = False
        pos.highest_seen = pos.avg_price
        pos.lowest_seen  = pos.avg_price
        if tag:
            pos.tag = tag
        log.info("Levels set for %s: SL=%.2f T1=%.2f(%d) T2=%.2f(%d) trail=%.3f%%",
                 pos.symbol, sl_price, t1_price, t1_qty, t2_price, t2_qty, trail_pct * 100)
        return True

    # ── Auto-exit monitor ─────────────────────────────────────────────────────

    def check_auto_exits(self, ltp_cache: Dict[str, float]) -> List[dict]:
        """
        Called by the background monitor task every ~3 s.
        Checks each open position against its SL/T1/T2 levels and fires exits.
        Returns a list of event dicts for the caller to broadcast.
        """
        if self.halted:
            return []

        events: List[dict] = []

        # ── Daily loss cap check ─────────────────────────────────────────────
        total_realised = sum(p.realised_pnl for p in self._positions)
        if total_realised < -self.daily_loss_cap:
            for p in list(self._positions):
                if p.is_open:
                    ltp = ltp_cache.get(p.symbol) or ltp_cache.get(p.stock) or p.avg_price
                    try:
                        self._partial_exit_at_price(p, p.qty, ltp, tag="daily-cap")
                        p.is_open = False
                        p.closed_at = datetime.now().strftime("%H:%M:%S")
                    except Exception as exc:
                        log.error("Daily-cap exit failed %s: %s", p.symbol, exc)
            self.halted = True
            events.append({"type": "DAILY_CAP_HIT",
                           "message": f"Daily loss cap Rs{self.daily_loss_cap:,.0f} hit — all positions closed, trading halted.",
                           "realised": round(total_realised, 2)})
            log.warning("Daily loss cap hit (Rs%.0f realised). Trading halted.", total_realised)
            return events

        # ── EOD square-off at 15:20 IST — algo closes all positions ─────────
        eod_open = [p for p in self._positions if p.is_open]
        if eod_open and _now_ist().time() >= _time(15, 20):
            for pos in eod_open:
                ltp = ltp_cache.get(pos.symbol) or ltp_cache.get(pos.stock) or pos.avg_price
                try:
                    self._partial_exit_at_price(pos, pos.qty, ltp, tag="eod-squareoff")
                    pos.is_open   = False
                    pos.closed_at = datetime.now().strftime("%H:%M:%S")
                    events.append({
                        "type":    "EOD_SQUAREOFF",
                        "symbol":  pos.symbol,
                        "pos_id":  pos.id,
                        "ltp":     ltp,
                        "message": f"EOD 15:20 square-off: {pos.symbol} closed @ Rs{ltp:,.2f} — intraday position auto-exited by algo",
                    })
                    log.info("EOD square-off %s @ Rs%.2f", pos.symbol, ltp)
                except Exception as exc:
                    log.error("EOD square-off failed %s: %s", pos.symbol, exc)
            return events

        # ── Per-position exit checks ─────────────────────────────────────────
        for pos in list(self._positions):
            if not pos.is_open or pos.sl_price is None:
                continue

            ltp = ltp_cache.get(pos.symbol) or ltp_cache.get(pos.stock)
            if not ltp or ltp <= 0:
                continue

            is_buy = pos.direction == "buy"

            # Update high/low watermark for trailing
            pos.highest_seen = max(pos.highest_seen or ltp, ltp)
            pos.lowest_seen  = min(pos.lowest_seen  or ltp, ltp)

            # ── Trailing SL update (once T2 is hit) ─────────────────────────
            if pos.t2_hit and pos.trail_pct > 0:
                if is_buy:
                    trail_sl = pos.highest_seen * (1 - pos.trail_pct)
                    new_sl = max(pos.sl_price, round(trail_sl, 2))
                else:
                    trail_sl = pos.lowest_seen * (1 + pos.trail_pct)
                    new_sl = min(pos.sl_price, round(trail_sl, 2))
                if new_sl != pos.sl_price:
                    log.debug("Trail SL updated %s: %.2f -> %.2f", pos.symbol, pos.sl_price, new_sl)
                    pos.sl_price = new_sl

            # ── T1 partial exit ──────────────────────────────────────────────
            if not pos.t1_hit and pos.t1_price is not None:
                t1_triggered = (is_buy and ltp >= pos.t1_price) or (not is_buy and ltp <= pos.t1_price)
                if t1_triggered and pos.t1_qty > 0 and pos.qty > pos.t1_qty:
                    self._partial_exit_at_price(pos, pos.t1_qty, ltp, tag="T1-hit")
                    pos.t1_hit   = True
                    pos.sl_price = pos.avg_price  # move SL to breakeven
                    events.append({
                        "type": "T1_HIT", "symbol": pos.symbol, "pos_id": pos.id,
                        "ltp": ltp, "qty": pos.t1_qty, "sl_moved_to": pos.sl_price,
                        "message": f"T1 hit: {pos.symbol} @ Rs{ltp:,.2f} — {pos.t1_qty} shares sold, SL moved to breakeven Rs{pos.avg_price:,.2f}",
                    })
                    log.info("T1 hit %s @ Rs%.2f, sold %d, SL -> BE Rs%.2f",
                             pos.symbol, ltp, pos.t1_qty, pos.avg_price)
                    continue  # re-evaluate next tick

            # ── T2 partial exit (only after T1) ─────────────────────────────
            elif pos.t1_hit and not pos.t2_hit and pos.t2_price is not None:
                t2_triggered = (is_buy and ltp >= pos.t2_price) or (not is_buy and ltp <= pos.t2_price)
                if t2_triggered and pos.t2_qty > 0 and pos.qty > pos.t2_qty:
                    self._partial_exit_at_price(pos, pos.t2_qty, ltp, tag="T2-hit")
                    pos.t2_hit = True
                    # Move SL to T1 to lock in partial gain
                    if pos.t1_price is not None:
                        pos.sl_price = pos.t1_price if is_buy else pos.t1_price
                    events.append({
                        "type": "T2_HIT", "symbol": pos.symbol, "pos_id": pos.id,
                        "ltp": ltp, "qty": pos.t2_qty, "sl_moved_to": pos.sl_price,
                        "message": f"T2 hit: {pos.symbol} @ Rs{ltp:,.2f} — {pos.t2_qty} shares sold, SL locked at T1 Rs{pos.sl_price:,.2f}. Trailing remainder.",
                    })
                    log.info("T2 hit %s @ Rs%.2f, sold %d, SL -> T1 Rs%.2f",
                             pos.symbol, ltp, pos.t2_qty, pos.sl_price)
                    continue

            # ── SL exit ──────────────────────────────────────────────────────
            sl_triggered = (is_buy and ltp <= pos.sl_price) or (not is_buy and ltp >= pos.sl_price)
            if sl_triggered:
                sl_was = pos.sl_price
                tag = "trail-SL" if pos.t2_hit else ("BE-SL" if pos.t1_hit else "initial-SL")
                try:
                    self._partial_exit_at_price(pos, pos.qty, ltp, tag=tag)
                    pos.is_open   = False
                    pos.closed_at = datetime.now().strftime("%H:%M:%S")
                    events.append({
                        "type": "SL_HIT", "symbol": pos.symbol, "pos_id": pos.id,
                        "ltp": ltp, "sl_was": sl_was, "tag": tag,
                        "message": f"SL hit ({tag}): {pos.symbol} @ Rs{ltp:,.2f} — position closed. SL was Rs{sl_was:,.2f}",
                    })
                    log.info("SL hit %s @ Rs%.2f [%s]", pos.symbol, ltp, tag)
                except Exception as exc:
                    log.error("SL exit failed %s: %s", pos.symbol, exc)

        return events

    # ── Capital plan helper ───────────────────────────────────────────────────

    @staticmethod
    def calc_qty(capital_slot: float, risk_per_trade: float,
                 entry_price: float, sl_price: float,
                 capital_cap_pct: float = 0.40) -> int:
        """
        Fixed-fractional position sizing.
        Returns minimum of risk-based qty and capital-cap qty.
        """
        risk_per_share = abs(entry_price - sl_price)
        if risk_per_share <= 0 or entry_price <= 0:
            return 1
        qty_by_risk  = int(risk_per_trade / risk_per_share)
        qty_by_cap   = int((capital_slot * capital_cap_pct) / entry_price)
        return max(1, min(qty_by_risk, qty_by_cap))

    # ── Query ─────────────────────────────────────────────────────────────────

    def summary(self, ltp_cache: Dict[str, float]) -> dict:
        open_positions = [p for p in self._positions if p.is_open]
        unrealised = 0.0
        invested   = 0.0
        enriched   = []
        for p in open_positions:
            ltp = ltp_cache.get(p.symbol) or ltp_cache.get(p.stock) or p.avg_price
            if p.direction == "buy":
                unr = (ltp - p.avg_price) * p.qty
                invested += p.avg_price * p.qty
            else:
                unr = (p.avg_price - ltp) * p.qty
            unrealised += unr
            enriched.append({
                **self._pos_dict(p),
                "ltp":        round(ltp, 2),
                "unrealised": round(unr, 2),
            })

        realised  = sum(p.realised_pnl for p in self._positions)
        total_pnl = unrealised + realised
        equity    = self.starting_capital + total_pnl

        return {
            "starting_capital": self.starting_capital,
            "cash":             round(self.cash, 2),
            "invested":         round(invested, 2),
            "equity":           round(equity, 2),
            "unrealised_pnl":   round(unrealised, 2),
            "realised_pnl":     round(realised, 2),
            "total_pnl":        round(total_pnl, 2),
            "pnl_pct":          round((total_pnl / self.starting_capital) * 100, 2),
            "daily_loss_cap":   self.daily_loss_cap,
            "halted":           self.halted,
            "open_positions":   enriched,
            "closed_positions": [self._pos_dict(p) for p in self._positions if not p.is_open],
            "orders":           [self._order_dict(o) for o in self._orders],
        }

    def _pos_dict(self, p: PaperPosition) -> dict:
        return {
            "id": p.id, "stock": p.stock, "exchange": p.exchange,
            "product": p.product, "right": p.right, "strike": p.strike,
            "expiry": p.expiry, "symbol": p.symbol, "direction": p.direction,
            "qty": p.qty, "avg_price": p.avg_price, "is_open": p.is_open,
            "realised_pnl": round(p.realised_pnl, 2),
            "opened_at": p.opened_at, "closed_at": p.closed_at,
            "tag": p.tag,
            # SL/tier levels
            "sl_price": p.sl_price,
            "t1_price": p.t1_price, "t1_qty": p.t1_qty, "t1_hit": p.t1_hit,
            "t2_price": p.t2_price, "t2_qty": p.t2_qty, "t2_hit": p.t2_hit,
            "trail_pct": p.trail_pct,
        }

    def _order_dict(self, o: PaperOrder) -> dict:
        return {
            "id": o.id, "time": o.time, "stock": o.stock, "symbol": o.symbol,
            "action": o.action, "qty": o.qty, "fill_price": o.fill_price,
            "order_type": o.order_type, "product": o.product,
            "right": o.right, "strike": o.strike, "expiry": o.expiry,
            "status": o.status, "tag": o.tag,
        }

    # ── Multi-leg strategy trades ──────────────────────────────────────────────

    def enter_strategy(
        self,
        strategy_id:   str,
        strategy_name: str,
        stock:         str,
        exchange:      str,
        expiry:        str,
        legs:          List[dict],
        ltp_cache:     Dict[str, float],
        break_even_lower: Optional[float] = None,
        break_even_upper: Optional[float] = None,
    ) -> dict:
        self._seq += 1
        strat_seq   = self._seq
        filled_legs = []
        net_credit  = 0.0

        for leg in legs:
            right  = leg.get("right")
            strike = leg.get("strike")
            prod   = leg.get("product", "options")
            action = leg["action"]
            qty    = leg["qty"]
            price  = float(leg.get("price", 0))

            order = self.place_order(
                stock=stock, exchange=exchange, product=prod,
                action=action, qty=qty, order_type="limit" if price else "market",
                price=price, ltp_cache=ltp_cache,
                right=right, strike=strike, expiry=expiry if prod == "options" else None,
            )
            signed = order.fill_price * qty
            net_credit += signed if action == "sell" else -signed
            filled_legs.append({
                "pos_id":     f"PP{strat_seq:04d}",
                "label":      leg.get("label", f"{action} {right or ''} {strike or ''}"),
                "action":     action, "right": right, "strike": strike,
                "product":    prod, "qty": qty,
                "fill_price": order.fill_price, "order_id": order.id,
            })

        trade = {
            "id":               f"ST{strat_seq:04d}",
            "strategy_id":      strategy_id,
            "strategy_name":    strategy_name,
            "stock":            stock, "exchange": exchange, "expiry": expiry,
            "legs":             filled_legs,
            "net_credit":       round(net_credit, 2),
            "status":           "open",
            "opened_at":        datetime.now().strftime("%H:%M:%S"),
            "closed_at":        None, "realised_pnl": None, "alerts": [],
            "break_even_lower": break_even_lower, "break_even_upper": break_even_upper,
        }
        self._strategy_trades.append(trade)
        log.info("Paper strategy entered: %s %s net_credit=%.2f", strategy_name, stock, net_credit)
        return trade

    def exit_strategy(self, trade_id: str, ltp_cache: Dict[str, float]) -> Tuple[dict, float]:
        trade = next((t for t in self._strategy_trades if t["id"] == trade_id), None)
        if not trade or trade["status"] != "open":
            raise ValueError(f"Strategy trade '{trade_id}' not found or already closed.")

        net_exit_credit = 0.0
        for leg in trade["legs"]:
            pos = next(
                (p for p in self._positions
                 if p.is_open and p.symbol == _symbol_key(
                     trade["stock"], leg["product"], leg.get("right"),
                     leg.get("strike"), trade["expiry"] if leg["product"] == "options" else None)),
                None,
            )
            if not pos:
                continue
            exit_action = "sell" if pos.direction == "buy" else "buy"
            order = self.place_order(
                stock=trade["stock"], exchange=trade["exchange"],
                product=leg["product"], action=exit_action,
                qty=pos.qty, order_type="market", price=0,
                ltp_cache=ltp_cache, right=leg.get("right"),
                strike=leg.get("strike"),
                expiry=trade["expiry"] if leg["product"] == "options" else None,
            )
            signed = order.fill_price * pos.qty
            net_exit_credit += signed if exit_action == "sell" else -signed

        realised = trade["net_credit"] + net_exit_credit
        trade["status"]       = "closed"
        trade["closed_at"]    = datetime.now().strftime("%H:%M:%S")
        trade["realised_pnl"] = round(realised, 2)
        log.info("Paper strategy closed: %s  P&L=%.2f", trade["id"], realised)
        return trade, realised

    def strategy_summary(self, ltp_cache: Dict[str, float]) -> List[dict]:
        result = []
        for trade in self._strategy_trades:
            unr = 0.0
            if trade["status"] == "open":
                for leg in trade["legs"]:
                    sym = _symbol_key(
                        trade["stock"], leg["product"], leg.get("right"),
                        leg.get("strike"),
                        trade["expiry"] if leg["product"] == "options" else None,
                    )
                    ltp = ltp_cache.get(sym) or ltp_cache.get(trade["stock"]) or leg["fill_price"]
                    signed = ltp * leg["qty"]
                    unr += signed if leg["action"] == "sell" else -signed
                trade_copy = {**trade, "unrealised_pnl": round(trade["net_credit"] + unr, 2)}
            else:
                trade_copy = {**trade, "unrealised_pnl": None}
            result.append(trade_copy)
        return result

    def check_alerts(self, ltp_cache: Dict[str, float]) -> List[dict]:
        new_alerts = []
        for trade in self._strategy_trades:
            if trade["status"] != "open":
                continue
            summary = self.strategy_summary(ltp_cache)
            t = next((s for s in summary if s["id"] == trade["id"]), None)
            if t is None:
                continue
            pnl    = t["unrealised_pnl"] or 0.0
            credit = trade["net_credit"]
            fired  = {a["type"] for a in trade["alerts"]}

            if credit > 0:
                # Take profit at 40% of credit — lock in gains early
                if pnl >= credit * 0.40 and "TARGET_40" not in fired:
                    alert = {"type": "TARGET_40", "trade_id": trade["id"],
                             "message": f"Target 40%: {trade['strategy_name']} {trade['stock']} P&L Rs{pnl:,.0f}",
                             "level": "success", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert); new_alerts.append(alert)
                # SL at 1× credit — exit at breakeven on premium, no deeper
                if pnl <= -credit and "SL_1X" not in fired:
                    alert = {"type": "SL_1X", "trade_id": trade["id"],
                             "message": f"SL 1x: {trade['strategy_name']} {trade['stock']} P&L Rs{pnl:,.0f}",
                             "level": "danger", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert); new_alerts.append(alert)
            elif credit < 0:
                debit = -credit
                # Take profit at 70% of max debit — reasonable for spread strategies
                if pnl >= debit * 0.70 and "TARGET_70" not in fired:
                    alert = {"type": "TARGET_70", "trade_id": trade["id"],
                             "message": f"Target 70%: {trade['strategy_name']} {trade['stock']} P&L Rs{pnl:,.0f}",
                             "level": "success", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert); new_alerts.append(alert)
                # SL at 40% of debit — cut loss before it doubles
                if pnl <= -debit * 0.40 and "SL_40" not in fired:
                    alert = {"type": "SL_40", "trade_id": trade["id"],
                             "message": f"SL 40%: {trade['strategy_name']} {trade['stock']} P&L Rs{pnl:,.0f}",
                             "level": "danger", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert); new_alerts.append(alert)
        return new_alerts

    # ── Strategy auto-exit (capital-preservation mode) ────────────────────────

    def check_strategy_auto_exits(self, ltp_cache: Dict[str, float]) -> List[dict]:
        """
        Auto-exits open strategy trades when SL or target is breached.
        Capital-preservation rules:
          Credit trades: exit at 40% profit OR when loss >= 1× credit
          Debit  trades: exit at 70% profit OR when loss >= 40% of debit
          All trades:    EOD square-off at 15:20 IST
        Returns events to broadcast via WebSocket.
        """
        events: List[dict] = []
        summary = self.strategy_summary(ltp_cache)
        now_time = _now_ist().time()
        is_eod   = now_time >= _time(15, 20)

        for trade in list(self._strategy_trades):
            if trade["status"] != "open":
                continue
            t = next((s for s in summary if s["id"] == trade["id"]), None)
            if t is None:
                continue

            pnl    = t["unrealised_pnl"] or 0.0
            credit = trade["net_credit"]
            reason = None

            if is_eod:
                reason = "EOD 15:20 square-off"
            elif credit > 0:
                if pnl >= credit * 0.40:
                    reason = f"Target 40% hit (P&L Rs{pnl:,.0f})"
                elif pnl <= -credit:
                    reason = f"SL 1× credit hit (P&L Rs{pnl:,.0f})"
            elif credit < 0:
                debit = -credit
                if pnl >= debit * 0.70:
                    reason = f"Target 70% hit (P&L Rs{pnl:,.0f})"
                elif pnl <= -debit * 0.40:
                    reason = f"SL 40% debit hit (P&L Rs{pnl:,.0f})"

            if reason is None:
                continue

            try:
                closed_trade, realised = self.exit_strategy_trade(trade["id"], ltp_cache)
                events.append({
                    "type":    "paper_strategy_closed",
                    "trade_id": trade["id"],
                    "strategy": trade["strategy_name"],
                    "stock":    trade["stock"],
                    "realised": round(realised, 2),
                    "reason":   reason,
                    "message":  f"Auto-exit: {trade['strategy_name']} {trade['stock']} — {reason} → P&L Rs{realised:,.0f}",
                })
                log.info("Strategy auto-exit %s %s: %s  realised=%.2f",
                         trade["strategy_name"], trade["stock"], reason, realised)
            except Exception as exc:
                log.error("Strategy auto-exit failed %s: %s", trade["id"], exc)

        return events

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.cash = self.starting_capital
        self._orders.clear()
        self._positions.clear()
        self._strategy_trades.clear()
        self._seq    = 0
        self.halted  = False
        log.info("Paper portfolio reset. Starting capital Rs%,.0f", self.starting_capital)
