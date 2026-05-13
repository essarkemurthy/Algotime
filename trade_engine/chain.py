import logging
from datetime import date

import pandas as pd

from .session import BreezeSession
from .symbols import SymbolBuilder

log = logging.getLogger(__name__)


class OptionChainFetcher:
    def __init__(self, session: BreezeSession) -> None:
        self.session = session

    def fetch(self, expiry: date, right: str = "others") -> pd.DataFrame:
        cfg  = self.session.cfg
        resp = self.session.api.get_option_chain_quotes(
            stock_code=cfg.underlying,
            exchange_code=cfg.exchange,
            product_type="options",
            expiry_date=SymbolBuilder.breeze_dt(expiry),
            right=right,
            strike_price="0",   # 0 = all strikes
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Option chain fetch failed: {resp}")

        df = pd.DataFrame(resp["Success"])
        df["strike_price"]  = df["strike_price"].astype(float).astype(int)
        df["ltp"]           = pd.to_numeric(df["ltp"],           errors="coerce")
        df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce")
        df["volume"]        = pd.to_numeric(df["volume"],        errors="coerce")
        df["right"]         = df["right"].str.lower().str.strip()
        return df.dropna(subset=["ltp"]).reset_index(drop=True)

    def atm_strike(self, spot: float, chain: pd.DataFrame) -> int:
        step      = self.session.cfg.strike_step
        rounded   = round(spot / step) * step
        available = chain["strike_price"].unique()
        atm       = int(min(available, key=lambda s: abs(s - rounded)))
        log.info("Spot %.2f → ATM %d", spot, atm)
        return atm
