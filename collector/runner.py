import logging
import signal
import threading
import time
from datetime import datetime

import schedule
from breeze_connect import BreezeConnect

from .chain import ChainSnapshotCollector
from .config import CollectorConfig
from .depth import DepthSnapshotCollector
from .futures import FuturesCollector
from .historical import HistoricalBackfill
from .iv_eod import EODRecorder
from .spot import SpotTickCollector
from .store import DataStore

log = logging.getLogger(__name__)


class TickMultiplexer:
    """
    Single on_ticks callback assigned to the Breeze WebSocket.
    Dispatches every incoming tick to all registered handlers.
    """

    def __init__(self) -> None:
        self._handlers: list = []

    def add(self, fn) -> None:
        self._handlers.append(fn)

    def __call__(self, tick: dict) -> None:
        for fn in self._handlers:
            try:
                fn(tick)
            except Exception as exc:
                log.error("Tick handler error: %s", exc)


class DataCollectorRunner:
    """
    Orchestrates the full collection day:

      Startup
        1. Connect Breeze + PostgreSQL
        2. Historical backfill (REST, fills gaps from last N days)
        3. Start WebSocket: spot ticks + futures ticks (via TickMultiplexer)
        4. Take first chain + depth snapshot immediately

      Intraday (scheduled)
        5. Option chain snapshots every chain_interval_sec
        6. Market depth snapshots every depth_interval_sec
        7. EOD IV recording at market_close

      Shutdown
        8. Flush incomplete candles, close DB pool

    Thread model:
      main thread     — schedule loop, EOD check, shutdown watcher
      spot-consumer   — drains spot tick queue → spot_ticks + candles
      futures-consumer— drains futures tick queue → futures_ticks + futures_candles
      Breeze SDK      — WebSocket callbacks → TickMultiplexer
    """

    def __init__(self, cfg: CollectorConfig) -> None:
        self.cfg       = cfg
        self._stop     = threading.Event()
        self._api: BreezeConnect | None          = None
        self._store: DataStore | None            = None
        self._spot: SpotTickCollector | None     = None
        self._futures: FuturesCollector | None   = None
        self._chain: ChainSnapshotCollector | None = None
        self._depth: DepthSnapshotCollector | None = None
        self._eod: EODRecorder | None            = None
        self._eod_done = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        log.info("Connecting to Breeze…")
        self._api = BreezeConnect(api_key=self.cfg.api_key)
        self._api.generate_session(
            api_secret=self.cfg.api_secret,
            session_token=self.cfg.session_token,
        )
        log.info("Breeze session established.")

        self._store   = DataStore(self.cfg.db_url)
        self._spot    = SpotTickCollector(self._api, self.cfg, self._store)
        self._chain   = ChainSnapshotCollector(self._api, self.cfg, self._store)
        self._eod     = EODRecorder(self.cfg, self._store)

        if self.cfg.collect_depth:
            self._depth = DepthSnapshotCollector(self._api, self.cfg, self._store)

        if self.cfg.futures_symbols:
            self._futures = FuturesCollector(self._api, self.cfg, self._store)

    def run(self) -> None:
        if self._api is None:
            raise RuntimeError("Call connect() before run().")

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except (OSError, ValueError):
                pass

        # Historical backfill before market opens
        if self.cfg.collect_historical:
            try:
                HistoricalBackfill(self._api, self.cfg, self._store).run()
            except Exception as exc:
                log.error("Historical backfill failed: %s", exc, exc_info=True)

        # Wire WebSocket — single multiplexed callback
        mux = TickMultiplexer()
        mux.add(self._spot.enqueue_tick)
        if self._futures:
            mux.add(self._futures.enqueue_tick)
        self._api.on_ticks = mux
        self._api.ws_connect()
        log.info("WebSocket connected.")

        # Start consumer threads + subscribe to feeds
        self._spot.start()
        if self._futures:
            self._futures.start()

        # First snapshot immediately, then on schedule
        self._run_chain_snapshot()
        schedule.every(self.cfg.chain_interval_sec).seconds.do(self._run_chain_snapshot)
        log.info("Chain snapshots every %ds.", self.cfg.chain_interval_sec)

        if self._depth:
            self._run_depth_snapshot()
            schedule.every(self.cfg.depth_interval_sec).seconds.do(self._run_depth_snapshot)
            log.info("Depth snapshots every %ds.", self.cfg.depth_interval_sec)

        log.info("Collector running. Shutdown at %s IST.", self.cfg.shutdown_at)
        while not self._stop.is_set():
            now = datetime.now().time()

            if now >= self.cfg.shutdown_at:
                log.info("Reached shutdown time %s — stopping.", self.cfg.shutdown_at)
                break

            if now >= self.cfg.market_close and not self._eod_done:
                self._eod.record()
                self._eod_done = True

            schedule.run_pending()
            time.sleep(1)

        self._shutdown()

    def _handle_signal(self, signum, _frame) -> None:
        log.info("Signal %s received — initiating shutdown.", signum)
        self._stop.set()

    def _run_chain_snapshot(self) -> None:
        try:
            self._chain.run_once()
        except Exception as exc:
            log.error("Chain snapshot run failed: %s", exc, exc_info=True)

    def _run_depth_snapshot(self) -> None:
        try:
            self._depth.run_once()
        except Exception as exc:
            log.error("Depth snapshot run failed: %s", exc, exc_info=True)

    def _shutdown(self) -> None:
        log.info("Shutting down collector…")
        schedule.clear()

        self._spot.stop()
        if self._futures:
            self._futures.stop()

        if not self._eod_done and self._eod:
            try:
                self._eod.record()
            except Exception as exc:
                log.error("EOD record on shutdown failed: %s", exc)

        if self._store:
            self._store.close()

        log.info("Collector shut down cleanly.")
