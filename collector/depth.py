import logging
from datetime import datetime
from typing import List

from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)

# Breeze bid/ask field names for each depth level
_BID_PRICE = ["best_bid_price",  "best_bid_price2",  "best_bid_price3",  "best_bid_price4",  "best_bid_price5"]
_BID_QTY   = ["best_bid_qty",    "best_bid_qty2",    "best_bid_qty3",    "best_bid_qty4",    "best_bid_qty5"]
_ASK_PRICE = ["best_offer_price","best_offer_price2","best_offer_price3","best_offer_price4","best_offer_price5"]
_ASK_QTY   = ["best_offer_qty",  "best_offer_qty2",  "best_offer_qty3",  "best_offer_qty4",  "best_offer_qty5"]


class DepthSnapshotCollector:
    """
    Fetches 5-level bid/ask market depth via the Breeze REST quotes endpoint
    every depth_interval_sec seconds (driven by runner schedule).

    Collects depth for all index symbols and equity symbols.
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api   = api
        self._cfg   = cfg
        self._store = store

    def run_once(self) -> None:
        ts = datetime.now().astimezone()
        for symbol in self._cfg.all_spot_symbols:
            try:
                self._snapshot(symbol, ts)
            except Exception as exc:
                log.error("Depth snapshot failed for %s: %s", symbol, exc)

    def _snapshot(self, symbol: str, ts: datetime) -> None:
        resp = self._api.get_quotes(
            stock_code=self._cfg.breeze_code(symbol),
            exchange_code=self._cfg.nse_exchange,
            expiry_date="",
            product_type="cash",
            right="",
            strike_price="",
        )
        if resp.get("Status") != 200 or not resp.get("Success"):
            log.warning("Depth fetch returned no data for %s.", symbol)
            return

        data = resp["Success"][0]
        rows = _parse_depth(ts, symbol, data)
        if rows:
            self._store.insert_depth_snapshots(rows)
            log.debug("Depth snapshot: %s  levels=%d", symbol, len(rows))


def _parse_depth(ts: datetime, symbol: str, data: dict) -> List[dict]:
    rows = []
    for level in range(5):
        bid_p = _to_float(data.get(_BID_PRICE[level]))
        bid_q = _to_int(data.get(_BID_QTY[level]))
        ask_p = _to_float(data.get(_ASK_PRICE[level]))
        ask_q = _to_int(data.get(_ASK_QTY[level]))

        if bid_p is not None:
            rows.append({"ts": ts, "symbol": symbol, "side": "B",
                         "level": level + 1, "price": bid_p, "qty": bid_q})
        if ask_p is not None:
            rows.append({"ts": ts, "symbol": symbol, "side": "A",
                         "level": level + 1, "price": ask_p, "qty": ask_q})
    return rows


def _to_float(val) -> float | None:
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_int(val) -> int | None:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
