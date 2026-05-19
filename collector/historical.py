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
from typing import Dict, List, Optional

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

        now = datetime.now().replace(tzinfo=None)

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

    # ── date-range backfill (bypasses gap-fill, used for incremental year runs) ─

    def _probe(self, symbol: str) -> bool:
        """
        Check symbol availability without wasting API calls:
          1. DB-first: if we already have a candle within the last 5 days, symbol is good.
          2. Breeze probe: fetch last 3 calendar days of 1m data (1 API call, retried once).
        Returns True if symbol is available on Breeze.
        """
        # Check DB first — free, no API call consumed
        try:
            last_ts = self._store.get_candle_last_ts(symbol, "1m")
            if last_ts is not None:
                age_days = (datetime.now() - last_ts.replace(tzinfo=None)).days
                if age_days <= 5:
                    log.info("Probe %s: DB hit (last candle %d days ago) — skipping API probe",
                             symbol, age_days)
                    return True
        except Exception:
            pass   # store unavailable; fall through to API probe

        # API probe — try twice to handle transient Breeze errors
        now     = datetime.now()
        from_dt = now - timedelta(days=3)
        for attempt in range(2):
            try:
                rows = self._fetch_in_chunks(
                    stock_code=symbol,
                    exchange_code=self._cfg.nse_exchange,
                    product_type="cash",
                    interval="1minute",
                    from_dt=from_dt,
                    to_dt=now,
                )
                if rows:
                    return True
                log.warning("Probe %s attempt %d: 0 candles returned", symbol, attempt + 1)
            except Exception as exc:
                log.warning("Probe %s attempt %d failed: %s", symbol, attempt + 1, exc)
            if attempt == 0:
                time.sleep(2.0)   # brief pause before retry

        log.warning("Probe %s: symbol not available on Breeze — skipping", symbol)
        return False

    def run_range(
        self,
        from_dt: datetime,
        to_dt: datetime,
        symbols: List[str],
        on_item_done=None,   # callable(symbol, db_interval, total_candles_for_symbol)
    ) -> Dict[str, dict]:
        """
        Fetch OHLCV for an explicit date window without gap-fill heuristics.
        Existing rows are silently skipped (ON CONFLICT DO NOTHING).

        Returns:
            {symbol: {"candles": int, "available": bool, "error": str|None}}
        """
        results: Dict[str, dict] = {}
        for symbol in symbols:
            log.info("Probing availability for %s …", symbol)
            if not self._probe(symbol):
                log.warning("Skipping %s — not available on Breeze", symbol)
                results[symbol] = {"candles": 0, "available": False,
                                   "error": "Probe returned 0 candles"}
                # advance progress counter so the UI bar still moves
                if on_item_done:
                    for ivl in self._cfg.historical_intervals:
                        on_item_done(symbol, _INTERVAL_TO_DB.get(ivl, ivl), 0)
                continue

            total, last_err = 0, None
            for breeze_interval in self._cfg.historical_intervals:
                db_interval = _INTERVAL_TO_DB.get(breeze_interval, breeze_interval)
                try:
                    rows = self._fetch_in_chunks(
                        stock_code=symbol,
                        exchange_code=self._cfg.nse_exchange,
                        product_type="cash",
                        interval=breeze_interval,
                        from_dt=from_dt,
                        to_dt=to_dt,
                    )
                    candles = [c for c in (
                        _to_candle_row(r, symbol, db_interval) for r in rows
                    ) if c]
                    if candles:
                        self._store.insert_candles(candles)
                        total += len(candles)
                        log.info("Range %s [%s]: +%d candles", symbol, db_interval, len(candles))
                    else:
                        log.warning("Range %s [%s]: 0 candles returned by Breeze", symbol, db_interval)
                except Exception as exc:
                    log.error("Range %s [%s]: %s", symbol, breeze_interval, exc)
                    last_err = str(exc)

                if on_item_done:
                    on_item_done(symbol, db_interval, total)
                time.sleep(0.5)

            available = total > 0
            results[symbol] = {"candles": total, "available": available, "error": last_err}
            log.info("Range complete — %s: %d candles, available=%s", symbol, total, available)

        return results

    # ── spot ──────────────────────────────────────────────────────────────────

    def _backfill_spot(self, symbol: str, breeze_interval: str,
                       db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_candle_last_ts(symbol, db_interval)
        if last_ts is not None:
            last_ts = last_ts.replace(tzinfo=None)
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
        else:
            log.warning("Spot %s [%s]: Breeze returned 0 candles from %s to %s.",
                        symbol, db_interval,
                        fetch_from.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"))

    # ── futures ───────────────────────────────────────────────────────────────

    def _backfill_futures(self, symbol: str, expiry: date, breeze_interval: str,
                          db_interval: str, from_dt: datetime, to_dt: datetime) -> None:
        last_ts = self._store.get_futures_candle_last_ts(symbol, expiry, db_interval)
        if last_ts is not None:
            last_ts = last_ts.replace(tzinfo=None)
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
        else:
            log.warning("Futures %s %s [%s]: Breeze returned 0 candles.", symbol, expiry, db_interval)

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
