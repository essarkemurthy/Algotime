"""
paper_engine.py — In-memory paper trading engine.

Orders fill immediately at live LTP (market) or at the specified limit price.
No real orders are sent to Breeze.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

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
        self.starting_capital = starting_capital
        self.cash             = starting_capital
        self._orders:    List[PaperOrder]    = []
        self._positions: List[PaperPosition] = []
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

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self.cash = self.starting_capital
        self._orders.clear()
        self._positions.clear()
        self._seq = 0
        log.info("Paper portfolio reset. Starting capital ₹%,.0f", self.starting_capital)
