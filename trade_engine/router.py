import time
import logging
from datetime import date
from typing import List

import pandas as pd

from .session import BreezeSession
from .models import Leg
from .symbols import SymbolBuilder

log = logging.getLogger(__name__)

try:
    from breeze_strategies import BreezeStrategies as _BS
    _STRAT_AVAIL = True
except ImportError:
    _STRAT_AVAIL = False


def chain_ltp(chain: pd.DataFrame, strike: int, right_lower: str) -> float:
    """Extract LTP for a specific strike/right from the chain DataFrame."""
    rows = chain[(chain["strike_price"] == strike) & (chain["right"] == right_lower)]
    if rows.empty:
        raise ValueError(f"No chain row found: strike={strike} right={right_lower}")
    return float(rows["ltp"].iloc[0])


def closest_delta_strike(df: pd.DataFrame, target_delta: float) -> int:
    """Return the strike whose |delta| is closest to target_delta."""
    diff = (df["delta"].abs() - target_delta).abs()
    return int(df.loc[diff.idxmin(), "strike_price"])


class OrderRouter:
    """Single-leg Breeze market orders with a short delay between legs."""

    def __init__(self, session: BreezeSession) -> None:
        self.session = session

    def place(self, leg: Leg) -> str:
        cfg  = self.session.cfg
        resp = self.session.api.place_order(
            stock_code=cfg.underlying,
            exchange_code=cfg.exchange,
            product="options",
            action=leg.action,
            order_type="market",
            stoploss="0",
            quantity=str(leg.quantity),
            price="0",
            validity="day",
            validity_date=SymbolBuilder.breeze_dt(date.today()),
            disclosed_quantity="0",
            expiry_date=SymbolBuilder.breeze_dt(leg.expiry),
            right="call" if leg.right == "CE" else "put",
            strike_price=str(leg.strike),
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Order failed for {leg.symbol}: {resp}")
        oid = resp["Success"]["order_id"]
        log.info("ORDER %s %s %d → id=%s", leg.action.upper(), leg.symbol, leg.strike, oid)
        return oid

    def execute(self, legs: List[Leg]) -> None:
        for leg in legs:
            leg.order_id = self.place(leg)
            time.sleep(0.2)   # avoid hitting Breeze rate limit on rapid sequential orders
