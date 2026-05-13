import logging
from typing import List

import pandas as pd

from .session import BreezeSession
from .router import OrderRouter
from .models import Leg, Position
from .symbols import SymbolBuilder
from .config import EngineConfig

log = logging.getLogger(__name__)


class StopLossManager:
    """
    Monitors a Position and triggers market-order exits on:
      • Debit-to-close ≥ stop_loss_multiplier × entry credit
      • P&L ≥ profit_target_pct × max_profit
      • |Net portfolio delta| > max_portfolio_delta
      • EOD force-flatten (called externally at exit_time)
    """

    def __init__(
        self,
        session: BreezeSession,
        router:  OrderRouter,
        cfg:     EngineConfig,
    ) -> None:
        self.session = session
        self.router  = router
        self.cfg     = cfg

    def close_cost(self, position: Position) -> float:
        """Current market debit to close all legs. Positive = costs money."""
        total = 0.0
        for leg in position.legs:
            resp = self.session.api.get_quotes(
                stock_code=self.session.cfg.underlying,
                exchange_code=self.session.cfg.exchange,
                expiry_date=SymbolBuilder.breeze_dt(leg.expiry),
                product_type="options",
                right="call" if leg.right == "CE" else "put",
                strike_price=str(leg.strike),
            )
            if resp.get("Status") != 200:
                log.warning("Quote failed for %s — skipping in cost calc.", leg.symbol)
                continue
            ltp  = float(resp["Success"][0]["ltp"])
            sign = 1 if leg.action == "sell" else -1   # buy back shorts (+), sell longs (−)
            total += sign * ltp * leg.quantity
        return total

    def net_pnl(self, position: Position) -> float:
        return position.net_credit - self.close_cost(position)

    def _net_delta(self, position: Position, chain: pd.DataFrame) -> float:
        total = 0.0
        for leg in position.legs:
            r = chain[
                (chain["strike_price"] == leg.strike) &
                (chain["right"] == ("call" if leg.right == "CE" else "put"))
            ]
            if r.empty or r["delta"].isna().all():
                continue
            raw_d = float(r["delta"].iloc[0])
            sign  = -1 if leg.action == "sell" else 1
            total += sign * raw_d * leg.quantity
        return total

    def _exit(self, position: Position, reason: str) -> None:
        log.warning("EXIT triggered — %s", reason)
        close_legs: List[Leg] = [
            Leg(
                action   = "buy" if l.action == "sell" else "sell",
                right    = l.right,
                strike   = l.strike,
                expiry   = l.expiry,
                symbol   = l.symbol,
                quantity = l.quantity,
            )
            for l in position.legs
        ]
        self.router.execute(close_legs)
        position.is_open = False
        log.info("Position closed. %s", reason)

    def check(self, position: Position, enriched_chain: pd.DataFrame) -> bool:
        """Returns True if the position was closed."""
        if not position.is_open:
            return False

        cc  = self.close_cost(position)
        pnl = position.net_credit - cc

        if cc >= self.cfg.stop_loss_multiplier * position.net_credit:
            self._exit(position, f"stop_loss  close_cost={cc:.2f}  limit={self.cfg.stop_loss_multiplier * position.net_credit:.2f}")
            return True

        profit_target = self.cfg.profit_target_pct * position.max_profit
        if pnl >= profit_target:
            self._exit(position, f"profit_target  pnl={pnl:.2f}  target={profit_target:.2f}")
            return True

        nd = self._net_delta(position, enriched_chain)
        if abs(nd) > self.cfg.max_portfolio_delta:
            self._exit(position, f"delta_breach  net_delta={nd:.2f}")
            return True

        log.info("Monitor OK | P&L=%.2f | close_cost=%.2f | Δ=%.2f", pnl, cc, nd)
        return False

    def force_flatten(self, position: Position) -> None:
        if position.is_open:
            self._exit(position, "force_flatten_eod")
