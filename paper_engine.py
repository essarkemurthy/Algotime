"""
paper_engine.py — In-memory paper trading engine.

Orders fill immediately at live LTP (market) or at the specified limit price.
No real orders are sent to Breeze.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("paper")


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


def _symbol_key(stock: str, product: str, right: Optional[str],
                strike: Optional[int], expiry: Optional[str]) -> str:
    if product == "options" and right and strike:
        return f"{stock}_{right}_{strike}_{expiry or ''}"
    return stock


class PaperTrader:
    """Simulated order book — fills instantly at LTP, tracks P&L mark-to-market."""

    def __init__(self, starting_capital: float = 1_000_000.0) -> None:
        self.starting_capital    = starting_capital
        self.cash                = starting_capital
        self._orders:            List[PaperOrder]    = []
        self._positions:         List[PaperPosition] = []
        self._strategy_trades:   List[dict]          = []
        self._seq = 0

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
    ) -> PaperOrder:
        """Fill a paper order. Returns the filled PaperOrder."""

        symbol = _symbol_key(stock, product, right, strike, expiry)

        # Determine fill price
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
            # Short sale — receive proceeds
            self.cash += cost

        self._seq += 1
        order = PaperOrder(
            id=f"P{self._seq:04d}",
            time=datetime.now().strftime("%H:%M:%S"),
            stock=stock, exchange=exchange, product=product,
            right=right, strike=strike, expiry=expiry, symbol=symbol,
            action=action, qty=qty, fill_price=round(fill_price, 2),
            order_type=order_type,
        )
        self._orders.append(order)

        self._update_positions(order)
        log.info("Paper %s %s ×%d @ ₹%.2f [%s]",
                 action.upper(), symbol, qty, fill_price, order.id)
        return order

    def _update_positions(self, order: PaperOrder) -> None:
        """Merge the fill into the position book."""
        # Find an open position with the same symbol and direction
        same_dir = next(
            (p for p in self._positions
             if p.is_open and p.symbol == order.symbol
             and p.direction == order.action),
            None,
        )
        # Find an open position in the opposite direction (close/reduce)
        opp_dir = next(
            (p for p in self._positions
             if p.is_open and p.symbol == order.symbol
             and p.direction != order.action),
            None,
        )

        if opp_dir:
            # Close or reduce the opposing position
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
                # Open a new position in the other direction with the remainder
                self._open_position(order, remainder)
        elif same_dir:
            # Add to existing position (average up/down)
            total_qty   = same_dir.qty + order.qty
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
        )
        self._positions.append(pos)

    # ── Exit ──────────────────────────────────────────────────────────────────

    def exit_position(self, pos_id: str, ltp_cache: Dict[str, float]) -> PaperOrder:
        pos = next((p for p in self._positions if p.id == pos_id and p.is_open), None)
        if not pos:
            raise ValueError(f"Open paper position '{pos_id}' not found.")
        exit_action = "sell" if pos.direction == "buy" else "buy"
        return self.place_order(
            stock=pos.stock, exchange=pos.exchange, product=pos.product,
            action=exit_action, qty=pos.qty, order_type="market", price=0,
            ltp_cache=ltp_cache, right=pos.right,
            strike=pos.strike, expiry=pos.expiry,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def summary(self, ltp_cache: Dict[str, float]) -> dict:
        open_positions = [p for p in self._positions if p.is_open]
        unrealised = 0.0
        invested   = 0.0
        enriched   = []
        for p in open_positions:
            ltp    = ltp_cache.get(p.symbol) or ltp_cache.get(p.stock) or p.avg_price
            if p.direction == "buy":
                unr = (ltp - p.avg_price) * p.qty
                invested += p.avg_price * p.qty
            else:
                unr = (p.avg_price - ltp) * p.qty
            unrealised += unr
            enriched.append({
                **self._pos_dict(p),
                "ltp":          round(ltp, 2),
                "unrealised":   round(unr, 2),
            })

        realised = sum(p.realised_pnl for p in self._positions)
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
            "open_positions":   enriched,
            "closed_positions": [
                self._pos_dict(p) for p in self._positions if not p.is_open
            ],
            "orders": [self._order_dict(o) for o in self._orders],
        }

    def _pos_dict(self, p: PaperPosition) -> dict:
        return {
            "id": p.id, "stock": p.stock, "exchange": p.exchange,
            "product": p.product, "right": p.right, "strike": p.strike,
            "expiry": p.expiry, "symbol": p.symbol, "direction": p.direction,
            "qty": p.qty, "avg_price": p.avg_price, "is_open": p.is_open,
            "realised_pnl": round(p.realised_pnl, 2),
            "opened_at": p.opened_at, "closed_at": p.closed_at,
        }

    def _order_dict(self, o: PaperOrder) -> dict:
        return {
            "id": o.id, "time": o.time, "stock": o.stock, "symbol": o.symbol,
            "action": o.action, "qty": o.qty, "fill_price": o.fill_price,
            "order_type": o.order_type, "product": o.product,
            "right": o.right, "strike": o.strike, "expiry": o.expiry,
            "status": o.status,
        }

    # ── Multi-leg strategy trades ──────────────────────────────────────────────

    def enter_strategy(
        self,
        strategy_id:  str,
        strategy_name: str,
        stock:        str,
        exchange:     str,
        expiry:       str,
        legs:         List[dict],          # each: {action, product, right, strike, qty, price}
        ltp_cache:    Dict[str, float],
        break_even_lower: Optional[float] = None,
        break_even_upper: Optional[float] = None,
    ) -> dict:
        """Place all legs of a multi-leg strategy atomically (paper fills)."""
        self._seq += 1
        strat_seq = self._seq
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
            # Credit/debit accounting
            signed = order.fill_price * qty
            net_credit += signed if action == "sell" else -signed
            filled_legs.append({
                "pos_id":     f"PP{strat_seq:04d}",
                "label":      leg.get("label", f"{action} {right or ''} {strike or ''}"),
                "action":     action,
                "right":      right,
                "strike":     strike,
                "product":    prod,
                "qty":        qty,
                "fill_price": order.fill_price,
                "order_id":   order.id,
            })

        trade = {
            "id":                f"ST{strat_seq:04d}",
            "strategy_id":       strategy_id,
            "strategy_name":     strategy_name,
            "stock":             stock,
            "exchange":          exchange,
            "expiry":            expiry,
            "legs":              filled_legs,
            "net_credit":        round(net_credit, 2),
            "status":            "open",
            "opened_at":         datetime.now().strftime("%H:%M:%S"),
            "closed_at":         None,
            "realised_pnl":      None,
            "alerts":            [],
            "break_even_lower":  break_even_lower,
            "break_even_upper":  break_even_upper,
        }
        self._strategy_trades.append(trade)
        log.info("Paper strategy entered: %s  %s  net_credit=%.2f",
                 strategy_name, stock, net_credit)
        return trade

    def exit_strategy(
        self, trade_id: str, ltp_cache: Dict[str, float]
    ) -> Tuple[dict, float]:
        """Close all open legs of a strategy trade."""
        trade = next((t for t in self._strategy_trades if t["id"] == trade_id), None)
        if not trade or trade["status"] != "open":
            raise ValueError(f"Strategy trade '{trade_id}' not found or already closed.")

        net_exit_credit = 0.0
        for leg in trade["legs"]:
            # Find matching open position
            pos = next(
                (p for p in self._positions
                 if p.is_open and p.symbol == _symbol_key(
                     trade["stock"], leg["product"], leg.get("right"),
                     leg.get("strike"), trade["expiry"] if leg["product"] == "options" else None
                 )),
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
        """Return all strategy trades with live unrealised P&L."""
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
        """Return new alert dicts for strategy trades crossing thresholds."""
        new_alerts = []
        for trade in self._strategy_trades:
            if trade["status"] != "open":
                continue
            summary = self.strategy_summary(ltp_cache)
            t = next((s for s in summary if s["id"] == trade["id"]), None)
            if t is None:
                continue
            pnl = t["unrealised_pnl"] or 0.0
            credit = trade["net_credit"]

            alerts_fired = set(a["type"] for a in trade["alerts"])

            # Iron Condor / credit strategies: target = 50% of credit, SL = 2x credit
            if credit > 0:
                if pnl >= credit * 0.5 and "TARGET_50" not in alerts_fired:
                    alert = {"type": "TARGET_50", "trade_id": trade["id"],
                             "message": f"🎯 {trade['strategy_name']} {trade['stock']} — 50% profit target hit (P&L ₹{pnl:,.0f})",
                             "level": "success", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert)
                    new_alerts.append(alert)
                if pnl <= -credit * 2 and "SL_2X" not in alerts_fired:
                    alert = {"type": "SL_2X", "trade_id": trade["id"],
                             "message": f"🛑 {trade['strategy_name']} {trade['stock']} — 2x stop-loss hit (P&L ₹{pnl:,.0f})",
                             "level": "danger", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert)
                    new_alerts.append(alert)

            # Debit strategies: SL = 50% of debit, target = 80% gain
            elif credit < 0:
                debit = -credit
                if pnl >= debit * 0.8 and "TARGET_80" not in alerts_fired:
                    alert = {"type": "TARGET_80", "trade_id": trade["id"],
                             "message": f"🎯 {trade['strategy_name']} {trade['stock']} — 80% gain hit (P&L ₹{pnl:,.0f})",
                             "level": "success", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert)
                    new_alerts.append(alert)
                if pnl <= -debit * 0.5 and "SL_50" not in alerts_fired:
                    alert = {"type": "SL_50", "trade_id": trade["id"],
                             "message": f"🛑 {trade['strategy_name']} {trade['stock']} — 50% stop-loss hit (P&L ₹{pnl:,.0f})",
                             "level": "danger", "ts": datetime.now().strftime("%H:%M:%S")}
                    trade["alerts"].append(alert)
                    new_alerts.append(alert)
        return new_alerts

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.cash = self.starting_capital
        self._orders.clear()
        self._positions.clear()
        self._strategy_trades.clear()
        self._seq = 0
        log.info("Paper portfolio reset. Starting capital ₹%,.0f", self.starting_capital)
