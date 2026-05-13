import logging
from datetime import date

import pandas as pd

from trade_engine.symbols import nearest_monthly_expiry, nearest_weekly_expiry

from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)


class EODRecorder:
    """
    Runs once at market_close (15:30 IST).
    For each symbol, pulls the last chain snapshot of the day, identifies the
    ATM call (delta closest to 0.5), computes IV Rank from iv_daily history,
    and writes one row to iv_daily.
    """

    def __init__(self, cfg: CollectorConfig, store: DataStore) -> None:
        self._cfg   = cfg
        self._store = store

    def record(self) -> None:
        today = date.today()
        log.info("EOD recording IV daily for %s", today)
        for symbol in self._cfg.symbols:
            expiry = (nearest_weekly_expiry()
                      if self._cfg.expiry_type(symbol) == "weekly"
                      else nearest_monthly_expiry())
            try:
                self._record_one(symbol, expiry, today)
            except Exception as exc:
                log.error("EOD IV record failed for %s: %s", symbol, exc, exc_info=True)

    def _record_one(self, symbol: str, expiry: date, today: date) -> None:
        result = self._store.get_last_atm_iv(symbol, expiry, today)
        if result is None:
            log.warning("No chain snapshot found for %s on %s — skipping iv_daily.", symbol, today)
            return

        atm_strike = result["atm_strike"]
        atm_iv     = result["atm_iv"]

        # IV Rank and percentile from historical iv_daily table
        history    = self._store.get_iv_history(symbol, lookback_days=252)
        iv_rank, iv_pctile = _compute_rank(atm_iv, history)

        self._store.insert_iv_daily({
            "date":       today,
            "symbol":     symbol,
            "expiry":     expiry,
            "atm_strike": atm_strike,
            "atm_iv":     atm_iv,
            "iv_rank":    round(iv_rank, 2),
            "iv_pctile":  round(iv_pctile, 2),
        })
        log.info(
            "iv_daily recorded: %-12s  expiry=%s  ATM=%d  IV=%.1f%%  Rank=%.1f  Pctile=%.1f",
            symbol, expiry, atm_strike, atm_iv * 100, iv_rank, iv_pctile,
        )


def _compute_rank(current_iv: float, history: pd.DataFrame) -> tuple:
    if history.empty or len(history) < 5:
        log.warning("IV history has %d rows — rank unreliable.", len(history))
        return 50.0, 50.0
    lo = history["atm_iv"].min()
    hi = history["atm_iv"].max()
    rank     = 50.0 if hi == lo else (current_iv - lo) / (hi - lo) * 100
    pctile   = float((history["atm_iv"] < current_iv).mean() * 100)
    return rank, pctile
