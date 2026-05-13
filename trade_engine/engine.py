import time
import logging
from datetime import datetime
from typing import Optional

from .config import EngineConfig
from .session import BreezeSession
from .chain import OptionChainFetcher
from .greeks import GreeksEngine, IVRankCalc
from .router import OrderRouter
from .risk import StopLossManager
from .models import Position
from .symbols import nearest_weekly_expiry, nearest_monthly_expiry
from .strategies import BullPutSpread, IronCondor

log = logging.getLogger(__name__)


class OptionsAlgoEngine:
    """
    Orchestrates the full trading day:
      1. connect()
      2. run_entry_scan()  — checks IV rank, enters if conditions met
      3. run_monitor_loop() — polls stop-loss / profit-target until EOD
      4. disconnect()
    """

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg      = cfg
        self.session  = BreezeSession(cfg)
        self.router:  Optional[OrderRouter]        = None
        self.fetcher: Optional[OptionChainFetcher] = None
        self.ge       = GreeksEngine(cfg)
        self.iv_rank  = IVRankCalc(cfg)
        self.position: Optional[Position]          = None

    def connect(self) -> None:
        self.session.connect()
        self.router  = OrderRouter(self.session)
        self.fetcher = OptionChainFetcher(self.session)

    def disconnect(self) -> None:
        self.session.disconnect()

    # ── entry ─────────────────────────────────────────────────────────────────
    def run_entry_scan(self) -> bool:
        """Returns True if a position was entered."""
        now = datetime.now().time()
        if not (self.cfg.entry_time <= now <= self.cfg.cutoff_time):
            log.info("Outside entry window (%s – %s) — no scan.",
                     self.cfg.entry_time, self.cfg.cutoff_time)
            return False

        spot   = self.session.get_spot()
        expiry = (nearest_weekly_expiry()
                  if self.cfg.expiry_type == "weekly"
                  else nearest_monthly_expiry())
        log.info("Underlying=%.2f  Expiry=%s  Strategy=%s",
                 spot, expiry, self.cfg.strategy)

        chain = self.fetcher.fetch(expiry)
        atm   = self.fetcher.atm_strike(spot, chain)

        atm_calls = chain[(chain["strike_price"] == atm) & (chain["right"] == "call")]
        if atm_calls.empty:
            log.warning("ATM call not found in chain — aborting scan.")
            return False

        atm_iv = self.ge.iv(float(atm_calls["ltp"].iloc[0]), spot, atm, expiry, "CE")
        if atm_iv is None:
            log.warning("Could not compute ATM IV — aborting scan.")
            return False

        self.iv_rank.record(atm_iv)
        ivr = self.iv_rank.rank(atm_iv)
        log.info("ATM IV=%.1f%%  IV Rank=%.1f  IV %%ile=%.1f",
                 atm_iv * 100, ivr, self.iv_rank.percentile(atm_iv))

        if ivr < self.cfg.min_iv_rank:
            log.info("IV Rank %.1f below minimum %.1f — low-vol environment, no trade.",
                     ivr, self.cfg.min_iv_rank)
            return False

        enriched = self.ge.enrich_chain(chain, spot, expiry)

        StrategyClass = BullPutSpread if self.cfg.strategy == "bull_put_spread" else IronCondor
        self.position = StrategyClass(self.session, self.router, self.cfg).enter(
            enriched, spot, expiry, atm
        )
        return self.position is not None

    # ── monitor ───────────────────────────────────────────────────────────────
    def run_monitor_loop(self, poll_seconds: int = 300) -> None:
        if not self.position:
            log.info("No open position to monitor.")
            return

        slm    = StopLossManager(self.session, self.router, self.cfg)
        expiry = self.position.legs[0].expiry

        while True:
            if datetime.now().time() >= self.cfg.exit_time:
                log.info("EOD exit time reached — force-flattening.")
                slm.force_flatten(self.position)
                break
            try:
                spot     = self.session.get_spot()
                chain    = self.fetcher.fetch(expiry)
                enriched = self.ge.enrich_chain(chain, spot, expiry)
                if slm.check(self.position, enriched):
                    break
            except Exception as exc:
                log.error("Monitor loop error: %s", exc, exc_info=True)

            time.sleep(poll_seconds)
