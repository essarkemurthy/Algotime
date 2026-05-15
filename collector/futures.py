import logging
import queue
import threading
import time
from datetime import date, datetime
from typing import Dict, List, Tuple

from trade_engine.symbols import SymbolBuilder, monthly_expiries

from .candles import CandleBuilder
from .config import CollectorConfig
from .store import DataStore

log = logging.getLogger(__name__)


class FuturesCollector:
    """
    Subscribes to Breeze WebSocket for near-month + next-month futures on
    every configured symbol.

    Ticks are enqueued by enqueue_tick() (called from the TickMultiplexer) and
    drained by a consumer thread that batches DB writes and builds 1m candles.
    """

    def __init__(self, api, cfg: CollectorConfig, store: DataStore) -> None:
        self._api      = api
        self._cfg      = cfg
        self._store    = store
        self._q: queue.Queue = queue.Queue(maxsize=100_000)
        self._candles: Dict[Tuple, CandleBuilder] = {}
        self._subscriptions: List[Tuple[str, date]] = []  # (symbol, expiry)
        self._running  = False
        self._thread: threading.Thread | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        expiries_map = self._build_expiry_map()

        for symbol, expiry in expiries_map:
            self._subscriptions.append((symbol, expiry))
            self._candles[(symbol, expiry)] = CandleBuilder(interval="1m")
            try:
                self._api.subscribe_feeds(
                    stock_code=symbol,
                    exchange_code=self._cfg.nfo_exchange,
                    product_type="futures",
                    expiry_date=SymbolBuilder.breeze_dt(expiry),
                    get_exchange_quotes=True,
                    get_market_depth=False,
                )
                log.info("Subscribed to %s futures %s.", symbol, expiry)
            except Exception as exc:
                log.error("Failed to subscribe %s futures %s: %s", symbol, expiry, exc)

        self._thread = threading.Thread(
            target=self._consume_loop, daemon=True, name="futures-consumer"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        for symbol, expiry in self._subscriptions:
            try:
                self._api.unsubscribe_feeds(
                    stock_code=symbol,
                    exchange_code=self._cfg.nfo_exchange,
                    product_type="futures",
                    expiry_date=SymbolBuilder.breeze_dt(expiry),
                )
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        for (symbol, expiry), builder in self._candles.items():
            leftovers = builder.flush_all()
            if leftovers:
                self._store.insert_futures_candles(leftovers)
                log.info("Flushed %d incomplete %s futures candles.", len(leftovers), symbol)

    def enqueue_tick(self, tick: dict) -> None:
        """Called by TickMultiplexer for every WebSocket message."""
        if tick.get("product_type", "") == "futures":
            try:
                self._q.put_nowait(tick)
            except queue.Full:
                log.warning("Futures tick queue full — dropping tick.")

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

        remaining: List[dict] = []
        while not self._q.empty():
            try:
                remaining.append(self._q.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._flush(remaining)

    def _flush(self, batch: List[dict]) -> None:
        valid_symbols = {sym for sym, _ in self._subscriptions}
        tick_rows: List[dict] = []

        for raw in batch:
            symbol = raw.get("stock_code", "")
            if symbol not in valid_symbols:
                continue

            ltp    = raw.get("last", raw.get("ltp", None))
            oi     = raw.get("open_interest", 0)
            volume = raw.get("total_quantity_traded", raw.get("volume", 0))
            ts_raw = raw.get("datetime", None)

            # Parse expiry from tick — Breeze sends it as a date string
            expiry = _parse_expiry(raw.get("expiry_date", ""))
            if expiry is None:
                continue
            if (symbol, expiry) not in self._candles:
                continue

            if ltp is None:
                continue

            ts = _parse_ts(ts_raw)
            try:
                ltp = float(ltp)
            except (TypeError, ValueError):
                continue

            tick_rows.append({
                "ts": ts, "symbol": symbol, "expiry": expiry,
                "ltp": ltp,
                "oi":     int(oi     or 0),
                "volume": int(volume or 0),
            })

            completed = self._candles[(symbol, expiry)].update(
                key=(symbol, expiry),
                symbol=symbol,
                ts=ts, ltp=ltp,
                volume=int(volume or 0),
                extra={"expiry": expiry},
            )
            if completed:
                try:
                    self._store.insert_futures_candle(completed)
                except Exception as exc:
                    log.error("Futures candle insert error: %s", exc)

        if tick_rows:
            try:
                self._store.insert_futures_ticks(tick_rows)
                log.debug("Flushed %d futures ticks.", len(tick_rows))
            except Exception as exc:
                log.error("Futures tick batch insert error: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_expiry_map(self) -> List[Tuple[str, date]]:
        """Returns [(symbol, expiry), ...] for all configured futures contracts."""
        result = []
        expiries = monthly_expiries(self._cfg.futures_num_expiries)
        for symbol in self._cfg.futures_symbols:
            for expiry in expiries:
                result.append((symbol, expiry))
        return result


def _parse_expiry(raw: str) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw[:len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    return None


def _parse_ts(ts_raw) -> datetime:
    if ts_raw is None:
        return datetime.now()
    if isinstance(ts_raw, datetime):
        return ts_raw
    try:
        return datetime.fromisoformat(str(ts_raw))
    except ValueError:
        return datetime.now()
