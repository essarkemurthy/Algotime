import logging
from typing import Optional

from breeze_connect import BreezeConnect

from .config import EngineConfig

log = logging.getLogger(__name__)


class BreezeSession:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._api: Optional[BreezeConnect] = None

    @property
    def api(self) -> BreezeConnect:
        if self._api is None:
            raise RuntimeError("Call connect() before using the API.")
        return self._api

    def connect(self) -> None:
        self._api = BreezeConnect(api_key=self.cfg.api_key)
        self._api.generate_session(
            api_secret=self.cfg.api_secret,
            session_token=self.cfg.session_token,
        )
        log.info("Breeze session established.")

    def disconnect(self) -> None:
        if self._api:
            try:
                self._api.ws_disconnect()
            except Exception:
                pass
            self._api = None
            log.info("Breeze session closed.")

    def __enter__(self) -> "BreezeSession":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    def get_spot(self) -> float:
        resp = self.api.get_quotes(
            stock_code=self.cfg.underlying,
            exchange_code="NSE",
            expiry_date="",
            product_type="cash",
            right="",
            strike_price="",
        )
        if resp.get("Status") != 200:
            raise RuntimeError(f"Spot fetch failed: {resp}")
        return float(resp["Success"][0]["ltp"])
