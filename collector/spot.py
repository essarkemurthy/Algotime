import logging
import queue
import threading
import time
from datetime import datetime
from typing import List

from .candles import CandleBuilder
from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)


class SpotTickCollector:
    """
    Subscribes to Breeze WebSocket feeds for all configured symbols (cash/spot).
    Ticks are pushed into a thread-safe queue by the SDK callback, then drained
    by a consumer thread that batches DB writes and builds 1-minute candles.
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api     = api
        self._cfg     = cfg
        self._store   = store
        self._q: queue.Queue = queue.Queue(maxsize=50_000)
        self._candles = CandleBuilder()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._api.on_ticks = self._on_tick
        self._api.ws_connect()
        for symbol in self._cfg.symbols:
            try:
                self._api.subscribe_feeds(
                    stock_code=symbol,
                    exchange_code=self._cfg.nse_exchange,
                    product_type="cash",
                    get_exchange_quotes=True,
                    get_market_depth=False,
                )
                log.info("Subscribed to %s spot feed.", symbol)
            except Exception as exc:
                log.error("Failed to subscribe %s: %s", symbol, exc)

        self._thread = threading.Thread(
            target=self._consume_loop, daemon=True, name="spot-consumer"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        for symbol in self._cfg.symbols:
            try:
                self._api.unsubscribe_feeds(
                    stock_code=symbol,
                    exchange_code=self._cfg.nse_exchange,
                    product_type="cash",
                )
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        # flush any incomplete candles before shutdown
        leftovers = self._candles.flush_all()
        if leftovers:
            self._store.insert_candles(leftovers)
            log.info("Flushed %d incomplete candles at shutdown.", len(leftovers))

    # ── WebSocket callback (runs in SDK thread) ───────────────────────────────

    def _on_tick(self, tick: dict) -> None:
        try:
            self._q.put_nowait(tick)
        except queue.Full:
            log.warning("Tick queue full — dropping tick.")

    # ── consumer thread ───────────────────────────────────────────────────────

    def _consume_loop(self) -> None:
        while self._running:
            batch: List[dict] = []
            deadline = time.monotonic() + self._cfg.spot_batch_sec
            while time.monotonic() < deadline:
                try:
                    batch.append(self._q.get(timeout=0.05))
                except queue.Empty:
                    pass
            if batch:
                self._flush(batch)

        # drain any remaining ticks after stop()
        remaining: List[dict] = []
        while not self._q.empty():
            try:
                remaining.append(self._q.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._flush(remaining)

    def _flush(self, batch: List[dict]) -> None:
        tick_rows: List[dict] = []

        for raw in batch:
            symbol = raw.get("stock_code", "")
            if symbol not in self._cfg.symbols:
                continue

            # Breeze field names vary slightly across versions — try both
            ltp    = raw.get("last", raw.get("ltp", None))
            volume = raw.get("total_quantity_traded", raw.get("volume", 0))
            ts_raw = raw.get("datetime", None)

            if ltp is None:
                continue

            ts = _parse_ts(ts_raw)
            try:
                ltp = float(ltp)
            except (TypeError, ValueError):
                continue

            tick_rows.append({
                "ts": ts, "symbol": symbol,
                "ltp": ltp, "volume": int(volume or 0),
            })

            completed = self._candles.update(symbol, ts, ltp, int(volume or 0))
            if completed:
                try:
                    self._store.insert_candle(completed)
                except Exception as exc:
                    log.error("Candle insert error: %s", exc)

        if tick_rows:
            try:
                self._store.insert_spot_ticks(tick_rows)
                log.debug("Flushed %d spot ticks.", len(tick_rows))
            except Exception as exc:
                log.error("Spot tick batch insert error: %s", exc)


def _parse_ts(ts_raw) -> datetime:
    if ts_raw is None:
        return datetime.now()
    if isinstance(ts_raw, datetime):
        return ts_raw
    try:
        return datetime.fromisoformat(str(ts_raw))
    except ValueError:
        return datetime.now()
