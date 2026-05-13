import logging
from datetime import date
from typing import Optional

import pandas as pd

from ..models import Leg, Position
from ..symbols import SymbolBuilder
from ..router import chain_ltp, closest_delta_strike
from .base import Strategy

log = logging.getLogger(__name__)


class BullPutSpread(Strategy):
    """
    Sell OTM put (short_strike) / Buy further OTM put (long_strike).
    Defined-risk credit spread. Max profit = credit. Max loss = spread_width - credit.
    """

    def enter(
        self,
        chain:  pd.DataFrame,
        spot:   float,
        expiry: date,
        atm:    int,
    ) -> Optional[Position]:
        cfg = self.cfg

        puts_below = chain[
            (chain["right"] == "put") &
            (chain["strike_price"] < atm) &
            chain["delta"].notna()
        ].copy()

        if puts_below.empty:
            log.warning("No OTM puts with computed delta — skipping BPS.")
            return None

        short_s = closest_delta_strike(puts_below, cfg.short_delta_target)
        long_s  = short_s - cfg.spread_width

        short_p = chain_ltp(chain, short_s, "put")
        long_p  = (chain_ltp(chain, long_s, "put")
                   if long_s in chain["strike_price"].values else 0.0)
        credit  = short_p - long_p

        if credit < cfg.spread_width * cfg.min_credit_pct:
            log.info("BPS credit %.2f < min %.2f — skipping.", credit,
                     cfg.spread_width * cfg.min_credit_pct)
            return None

        qty  = cfg.lot_size * cfg.num_lots
        legs = [
            Leg("sell", "PE", short_s, expiry,
                SymbolBuilder.build(cfg.underlying, expiry, short_s, "PE", cfg.expiry_type),
                qty, short_p),
            Leg("buy",  "PE", long_s,  expiry,
                SymbolBuilder.build(cfg.underlying, expiry, long_s,  "PE", cfg.expiry_type),
                qty, long_p),
        ]
        self.router.execute(legs)

        pos = Position(
            legs       = legs,
            net_credit = credit * qty,
            max_risk   = (cfg.spread_width - credit) * qty,
            max_profit = credit * qty,
            strategy   = "bull_put_spread",
        )
        log.info("BPS entered: sell %dPE / buy %dPE | credit=%.2f max_risk=%.2f",
                 short_s, long_s, pos.net_credit, pos.max_risk)
        return pos
