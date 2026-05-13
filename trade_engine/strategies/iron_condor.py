import logging
from datetime import date
from typing import Optional

import pandas as pd

from ..models import Leg, Position
from ..symbols import SymbolBuilder
from ..router import chain_ltp, closest_delta_strike
from .base import Strategy

log = logging.getLogger(__name__)


class IronCondor(Strategy):
    """
    Bull Put Spread (below market) + Bear Call Spread (above market).
    Collects premium from both sides. Max loss = larger spread_width - total credit.
    """

    def enter(
        self,
        chain:  pd.DataFrame,
        spot:   float,
        expiry: date,
        atm:    int,
    ) -> Optional[Position]:
        cfg = self.cfg

        puts  = chain[(chain["right"] == "put")  & (chain["strike_price"] < atm) & chain["delta"].notna()]
        calls = chain[(chain["right"] == "call") & (chain["strike_price"] > atm) & chain["delta"].notna()]

        if puts.empty or calls.empty:
            log.warning("Not enough chain data for Iron Condor.")
            return None

        ps = closest_delta_strike(puts,  cfg.short_delta_target)
        pl = ps - cfg.spread_width
        cs = closest_delta_strike(calls, cfg.short_delta_target)
        cl = cs + cfg.spread_width

        ps_p = chain_ltp(chain, ps, "put")
        pl_p = chain_ltp(chain, pl, "put")  if pl in chain["strike_price"].values else 0.0
        cs_p = chain_ltp(chain, cs, "call")
        cl_p = chain_ltp(chain, cl, "call") if cl in chain["strike_price"].values else 0.0
        credit = (ps_p - pl_p) + (cs_p - cl_p)

        if credit < cfg.spread_width * cfg.min_credit_pct:
            log.info("IC credit %.2f < min %.2f — skipping.", credit,
                     cfg.spread_width * cfg.min_credit_pct)
            return None

        qty = cfg.lot_size * cfg.num_lots
        et  = cfg.expiry_type
        legs = [
            Leg("sell","PE", ps, expiry, SymbolBuilder.build(cfg.underlying,expiry,ps,"PE",et), qty, ps_p),
            Leg("buy", "PE", pl, expiry, SymbolBuilder.build(cfg.underlying,expiry,pl,"PE",et), qty, pl_p),
            Leg("sell","CE", cs, expiry, SymbolBuilder.build(cfg.underlying,expiry,cs,"CE",et), qty, cs_p),
            Leg("buy", "CE", cl, expiry, SymbolBuilder.build(cfg.underlying,expiry,cl,"CE",et), qty, cl_p),
        ]
        self.router.execute(legs)

        pos = Position(
            legs       = legs,
            net_credit = credit * qty,
            max_risk   = (cfg.spread_width - credit) * qty,
            max_profit = credit * qty,
            strategy   = "iron_condor",
        )
        log.info("IC entered: puts %d/%d  calls %d/%d | credit=%.2f",
                 ps, pl, cs, cl, pos.net_credit)
        return pos
