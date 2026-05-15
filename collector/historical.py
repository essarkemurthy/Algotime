"""
Historical OHLCV backfill using the Breeze get_historical_data_v2 REST endpoint.

Runs once on startup. For each symbol + interval combination, determines the
last stored timestamp and fetches only the missing range (gap-fill).

Intervals collected:
  1m, 5m, 15m, 30m  — past backfill_days (default 90)
  1d                 — past backfill_days_daily (default 730 = ~2 years)

Rate limiting: 0.5 s sleep between REST calls (~120 calls/min, well within Breeze limits).
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from trade_engine.symbols import SymbolBuilder, monthly_expiries

from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)

_INTERVAL_TO_DB = {
    "1minute":  "1m",
    "5minute":  "5m",
    "15minute": "15m",
    "30minute": "30m",
    "1day":     "1d",
}

_INTRADAY_INTERVALS = {"1minute", "5minute", "15minute", "30minute"}


class HistoricalBackfill:
    """
    Fetches OHLCV history from Breeze and inserts into:
      - candles (equity/index spot, all intervals)
      - futures_candles (futures contracts, all intervals)
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api   = api
        self._cfg   = cfg
        self._store = store

    def run(self) -> None:
        log.info("Starting historical backfill — intraday: %d days, daily: %d days",
                 self._cfg.backfill_days, self._cfg.backfill_days_daily)

        now = datetime.now()

        # Spot / index candles — all configured symbols
        for symbol in self._cfg.all_spot_symbols:
            for breeze_interval in self._cfg.historical_intervals:
                db_interval = _INTERVAL_TO_DB.get(breeze_interval, breeze_interval)
                days = (self._cfg.backfill_days_daily
                        if breeze_interval == "1day"
                        else self._cfg.backfill_days)
                from_dt = now - timedelta(days=days)
                self._backfill_spot(symbol, breeze_interval, db_interval, from_dt, now)
                time.sleep(0.5)

        # Futures candles — all configured futures symbols × all expiries
        for symbol in self._cfg.futures_symbols:
            for expiry in monthly_expiries(self._cfg.futures_num_expiries):
                for breeze_interval in self._cfg.historical_intervals:
                    db_interval = _INTERVAL_TO_DB.get(breeze_interval, breeze_interval)
                    days = (self._cfg.backfill_days_daily
                            if breeze_interval == "1day"
                            else self._cfg.backfill_days)
                    from_dt = now - timedelta(days=days)
                    self._backfill_futures(symbol, expiry, breeze_interval,
                                           db_interval, from_dt, now)
                    time.sleep(0.5)

        log.info("Historical backfill complete.")

    # ── spot ──────────────────────────────────────────────────────────────────

    def _backfill_spot(self, symbol: str, breeze_interval: str,
                       db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_candle_last_ts(symbol, db_interval)
        fetch_from = (last_ts + timedelta(minutes=1)) if last_ts else from_dt

        if fetch_from >= to_dt:
            log.debug("Spot %s %s up to date.", symbol, db_interval)
            return

        log.info("Backfilling spot %s [%s] from %s…",
                 symbol, db_interval, fetch_from.strftime("%Y-%m-%d"))

        rows = self._fetch_in_chunks(
            stock_code=symbol,
            exchange_code=self._cfg.nse_exchange,
            product_type="cash",
            interval=breeze_interval,
            from_dt=fetch_from,
            to_dt=to_dt,
        )
        candles = [_to_candle_row(r, symbol, db_interval) for r in rows]
        candles = [c for c in candles if c]
        if candles:
            self._store.insert_candles(candles)
            log.info("Spot %s [%s]: +%d candles.", symbol, db_interval, len(candles))

    # ── futures ───────────────────────────────────────────────────────────────

    def _backfill_futures(self, symbol: str, expiry: date, breeze_interval: str,
                          db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_futures_candle_last_ts(symbol, expiry, db_interval)
        fetch_from = (last_ts + timedelta(minutes=1)) if last_ts else from_dt

        if fetch_from >= to_dt:
            log.debug("Futures %s %s [%s] up to date.", symbol, expiry, db_interval)
            return

        log.info("Backfilling futures %s %s [%s] from %s…",
                 symbol, expiry, db_interval, fetch_from.strftime("%Y-%m-%d"))

        rows = self._fetch_in_chunks(
            stock_code=symbol,
            exchange_code=self._cfg.nfo_exchange,
            product_type="futures",
            interval=breeze_interval,
            from_dt=fetch_from,
            to_dt=to_dt,
            expiry_date=SymbolBuilder.breeze_dt(expiry),
        )
        candles = [_to_futures_candle_row(r, symbol, expiry, db_interval) for r in rows]
        candles = [c for c in candles if c]
        if candles:
            self._store.insert_futures_candles(candles)
            log.info("Futures %s %s [%s]: +%d candles.",
                     symbol, expiry, db_interval, len(candles))

    # ── Breeze REST — chunked to respect API date-range limits ───────────────

    def _fetch_in_chunks(self, stock_code: str, exchange_code: str,
                         product_type: str, interval: str,
                         from_dt: datetime, to_dt: datetime,
                         expiry_date: str = "",
                         right: str = "",
                         strike_price: str = "") -> List[dict]:
        """
        Breeze limits historical data to ~30 days per call for 1m data.
        We chunk the range into 25-day windows and concatenate.
        """
        chunk_days = 25 if interval in _INTRADAY_INTERVALS else 365
        all_rows: List[dict] = []
        cursor = from_dt

        while cursor < to_dt:
            end = min(cursor + timedelta(days=chunk_days), to_dt)
            try:
                resp = self._api.get_historical_data_v2(
                    interval=interval,
                    from_date=_breeze_dt(cursor),
                    to_date=_breeze_dt(end),
                    stock_code=stock_code,
                    exchange_code=exchange_code,
                    product_type=product_type,
                    expiry_date=expiry_date,
                    right=right,
                    strike_price=strike_price,
                )
                if resp.get("Status") == 200:
                    all_rows.extend(resp.get("Success") or [])
                else:
                    log.warning("Historical fetch non-200 for %s %s %s–%s: %s",
                                stock_code, interval,
                                cursor.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                                resp.get("Error", ""))
            except Exception as exc:
                log.error("Historical fetch error %s %s: %s", stock_code, interval, exc)

            cursor = end + timedelta(minutes=1)
            time.sleep(0.5)

        return all_rows


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
