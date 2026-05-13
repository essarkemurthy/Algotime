import os
import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from py_vollib.black_scholes.implied_volatility import implied_volatility as _bs_iv
from py_vollib.black_scholes.greeks.analytical import (
    delta as _delta,
    gamma as _gamma,
    theta as _theta,
    vega  as _vega,
)
from py_vollib_vectorized import vectorized_implied_volatility as _vec_iv

from .config import EngineConfig

log = logging.getLogger(__name__)


class GreeksEngine:
    def __init__(self, cfg: EngineConfig) -> None:
        self.r = cfg.risk_free_rate

    def tte(self, expiry: date) -> float:
        """Time to expiry as a fraction of a calendar year."""
        return max((expiry - date.today()).days, 1) / 365.0

    def iv(
        self,
        price:  float,
        spot:   float,
        strike: int,
        expiry: date,
        right:  str,
    ) -> Optional[float]:
        flag = "c" if right == "CE" else "p"
        try:
            v = _bs_iv(price, spot, strike, self.tte(expiry), self.r, flag)
            return float(v) if v and 0 < v < 5 else None
        except Exception:
            return None

    def greeks(
        self,
        iv:     float,
        spot:   float,
        strike: int,
        expiry: date,
        right:  str,
    ) -> dict:
        flag = "c" if right == "CE" else "p"
        t, r = self.tte(expiry), self.r
        return {
            "delta": _delta(flag, spot, strike, t, r, iv),
            "gamma": _gamma(flag, spot, strike, t, r, iv),
            "theta": _theta(flag, spot, strike, t, r, iv) / 365,   # per-day theta
            "vega":  _vega(flag, spot, strike, t, r, iv) / 100,    # per 1% IV move
        }

    def enrich_chain(
        self,
        chain:  pd.DataFrame,
        spot:   float,
        expiry: date,
    ) -> pd.DataFrame:
        """Add iv / delta / gamma / theta / vega columns using vectorized IV first."""
        df    = chain.copy()
        t     = self.tte(expiry)
        flags = np.where(df["right"].str.startswith("c"), "c", "p")

        try:
            ivs = _vec_iv(
                df["ltp"].values.astype(float),
                np.full(len(df), spot),
                df["strike_price"].values.astype(float),
                np.full(len(df), t),
                np.full(len(df), self.r),
                flags,
                q=np.zeros(len(df)),
                return_as="numpy",
                on_error="ignore",
            )
            df["iv"] = np.where((ivs > 0) & (ivs < 5), ivs, np.nan)
        except Exception as exc:
            log.warning("Vectorized IV error (%s) — row-by-row fallback.", exc)
            df["iv"] = [
                self.iv(
                    row.ltp, spot, row.strike_price, expiry,
                    "CE" if row.right.startswith("c") else "PE",
                )
                for row in df.itertuples()
            ]

        for col in ("delta", "gamma", "theta", "vega"):
            df[col] = np.nan

        for idx in df[df["iv"].notna()].index:
            row   = df.loc[idx]
            r_str = "CE" if str(row["right"]).startswith("c") else "PE"
            try:
                g = self.greeks(float(row["iv"]), spot, int(row["strike_price"]), expiry, r_str)
                for col, val in g.items():
                    df.at[idx, col] = val
            except Exception:
                pass

        return df


class IVRankCalc:
    """
    Maintains a rolling daily ATM IV history CSV.
    IV Rank  = (current - 1yr_low)  / (1yr_high - 1yr_low) × 100
    IV %ile  = % of days in past year where ATM IV < current
    """

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg

    def _load(self) -> pd.DataFrame:
        p = self.cfg.iv_history_file
        if not os.path.exists(p):
            return pd.DataFrame(columns=["date", "atm_iv"])
        return pd.read_csv(p, parse_dates=["date"])

    def record(self, atm_iv: float) -> None:
        os.makedirs(os.path.dirname(self.cfg.iv_history_file) or ".", exist_ok=True)
        df    = self._load()
        today = date.today().isoformat()
        if not df.empty and df.iloc[-1]["date"].date() == date.today():
            df.at[df.index[-1], "atm_iv"] = atm_iv
        else:
            df = pd.concat(
                [df, pd.DataFrame([{"date": today, "atm_iv": atm_iv}])],
                ignore_index=True,
            )
        df.tail(self.cfg.iv_rank_lookback * 2).to_csv(self.cfg.iv_history_file, index=False)

    def rank(self, current_iv: float) -> float:
        df = self._load().tail(self.cfg.iv_rank_lookback)
        if len(df) < 10:
            log.warning("IV history has %d rows — rank may be unreliable.", len(df))
        lo, hi = df["atm_iv"].min(), df["atm_iv"].max()
        return 50.0 if hi == lo else float((current_iv - lo) / (hi - lo) * 100)

    def percentile(self, current_iv: float) -> float:
        df = self._load().tail(self.cfg.iv_rank_lookback)
        return 50.0 if df.empty else float((df["atm_iv"] < current_iv).mean() * 100)
