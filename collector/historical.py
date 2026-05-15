"""
Historical OHLCV backfill using the Breeze get_historical_data_v2 REST endpoint.

Runs once on startup. For each symbol + interval combination, determines the
last stored timestamp and fetches only the missing range, avoiding re-fetching
data that already exists in the DB.

Rate limit: Breeze allows ~10 requests/second. We sleep 0.5s between calls.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from trade_engine.symbols import SymbolBuilder, monthly_expiries

from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)

# Map our interval names → Breeze API interval strings
_INTERVAL_MAP = {
    "1minute":  "1m",
    "5minute":  "5m",
    "15minute": "15m",
    "30minute": "30m",
    "1day":     "1d",
}

_BREEZE_INTERVAL_MAP = {
    "1m": "1minute",
    "5m": "5minute",
    "15m": "15minute",
    "1d": "1day",
}


class HistoricalBackfill:
    """
    Fetches OHLCV history from Breeze REST API and inserts into:
      - candles table (equity/index spot)
      - futures_candles table (futures contracts)
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api   = api
        self._cfg   = cfg
        self._store = store

    def run(self) -> None:
        log.info("Starting historical backfill (past %d days)…", self._cfg.backfill_days)
        from_dt = datetime.now() - timedelta(days=self._cfg.backfill_days)
        to_dt   = datetime.now()

        # Spot / index candles
        for symbol in self._cfg.all_spot_symbols:
            for breeze_interval in self._cfg.historical_intervals:
                db_interval = _INTERVAL_MAP.get(breeze_interval, breeze_interval)
                self._backfill_spot(symbol, breeze_interval, db_interval, from_dt, to_dt)
                time.sleep(0.5)

        # Futures candles — near-month + next-month
        for symbol in self._cfg.futures_symbols:
            for expiry in monthly_expiries(self._cfg.futures_num_expiries):
                for breeze_interval in self._cfg.historical_intervals:
                    db_interval = _INTERVAL_MAP.get(breeze_interval, breeze_interval)
                    self._backfill_futures(symbol, expiry, breeze_interval,
                                          db_interval, from_dt, to_dt)
                    time.sleep(0.5)

        log.info("Historical backfill complete.")

    # ── spot ──────────────────────────────────────────────────────────────────

    def _backfill_spot(self, symbol: str, breeze_interval: str,
                       db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_candle_last_ts(symbol, db_interval)
        # Fetch only the gap
        fetch_from = (last_ts + timedelta(minutes=1)) if last_ts else from_dt

        if fetch_from >= to_dt:
            log.debug("Spot %s %s already up to date.", symbol, db_interval)
            return

        log.info("Backfilling spot %s %s from %s…", symbol, db_interval,
                 fetch_from.strftime("%Y-%m-%d"))

        rows = self._fetch_historical(
            stock_code=symbol,
            exchange_code=self._cfg.nse_exchange,
            product_type="cash",
            interval=breeze_interval,
            from_dt=fetch_from,
            to_dt=to_dt,
        )
        candles = [_to_candle_row(r, symbol, db_interval) for r in rows if r]
        candles = [c for c in candles if c]

        if candles:
            self._store.insert_candles(candles)
            log.info("Spot %s %s: inserted %d candles.", symbol, db_interval, len(candles))
        else:
            log.info("Spot %s %s: no data returned.", symbol, db_interval)

    # ── futures ───────────────────────────────────────────────────────────────

    def _backfill_futures(self, symbol: str, expiry: date, breeze_interval: str,
                          db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_futures_candle_last_ts(symbol, expiry, db_interval)
        fetch_from = (last_ts + timedelta(minutes=1)) if last_ts else from_dt

        if fetch_from >= to_dt:
            log.debug("Futures %s %s %s already up to date.", symbol, expiry, db_interval)
            return

        log.info("Backfilling futures %s %s %s from %s…", symbol, expiry, db_interval,
                 fetch_from.strftime("%Y-%m-%d"))

        rows = self._fetch_historical(
            stock_code=symbol,
            exchange_code=self._cfg.nfo_exchange,
            product_type="futures",
            interval=breeze_interval,
            from_dt=fetch_from,
            to_dt=to_dt,
            expiry_date=SymbolBuilder.breeze_dt(expiry),
        )
        candles = [_to_futures_candle_row(r, symbol, expiry, db_interval)
                   for r in rows if r]
        candles = [c for c in candles if c]

        if candles:
            self._store.insert_futures_candles(candles)
            log.info("Futures %s %s %s: inserted %d candles.",
                     symbol, expiry, db_interval, len(candles))
        else:
            log.info("Futures %s %s %s: no data returned.", symbol, expiry, db_interval)

    # ── Breeze REST call ──────────────────────────────────────────────────────

    def _fetch_historical(self, stock_code: str, exchange_code: str,
                          product_type: str, interval: str,
                          from_dt: datetime, to_dt: datetime,
                          expiry_date: str = "",
                          right: str = "",
                          strike_price: str = "") -> List[dict]:
        try:
            resp = self._api.get_historical_data_v2(
                interval=interval,
                from_date=_breeze_dt(from_dt),
                to_date=_breeze_dt(to_dt),
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type=product_type,
                expiry_date=expiry_date,
                right=right,
                strike_price=strike_price,
            )
        except Exception as exc:
            log.error("Historical fetch error %s %s: %s", stock_code, interval, exc)
            return []

        if resp.get("Status") != 200:
            log.warning("Historical fetch non-200 for %s %s: %s",
                        stock_code, interval, resp.get("Error", ""))
            return []

        return resp.get("Success") or []


# ── row builders ──────────────────────────────────────────────────────────────

def _to_candle_row(raw: dict, symbol: str, interval: str) -> Optional[dict]:
    try:
        return {
            "symbol":   symbol,
            "interval": interval,
            "ts":       _parse_breeze_dt(raw.get("datetime")),
            "open":     float(raw["open"]),
            "high":     float(raw["high"]),
            "low":      float(raw["low"]),
            "close":    float(raw["close"]),
            "volume":   int(float(raw.get("volume", 0) or 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _to_futures_candle_row(raw: dict, symbol: str, expiry: date,
                           interval: str) -> Optional[dict]:
    row = _to_candle_row(raw, symbol, interval)
    if row:
        row["expiry"] = expiry
    return row


def _breeze_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_breeze_dt(raw) -> Optional[datetime]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw)[:19], fmt)
        except ValueError:
            continue
    return None
