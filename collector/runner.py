import logging
import signal
import threading
import time
from datetime import datetime

import schedule
from breeze_connect import BreezeConnect

from .chain import ChainSnapshotCollector
from .config import CollectorConfig
from .iv_eod import EODRecorder
from .spot import SpotTickCollector
from .store import DataStore

log = logging.getLogger(__name__)


class DataCollectorRunner:
    """
    Orchestrates the full collection day:
      1. Connects to Breeze and PostgreSQL
      2. Starts WebSocket spot feed (SpotTickCollector)
      3. Runs option chain REST snapshots on a 5-minute schedule
      4. Fires EODRecorder once at market_close
      5. Shuts down cleanly at shutdown_at or on Ctrl+C

    Thread model:
      Main thread  — schedule loop, EOD check, shutdown watcher
      spot-consumer (daemon) — drains tick queue → spot_ticks + candles_1m
      Breeze SDK thread — WebSocket callbacks → tick queue
    """

    def __init__(self, cfg: CollectorConfig) -> None:
        self.cfg   = cfg
        self._stop = threading.Event()
        self._api: BreezeConnect | None   = None
        self._store: DataStore | None     = None
        self._spot: SpotTickCollector | None  = None
        self._chain: ChainSnapshotCollector | None = None
        self._eod: EODRecorder | None     = None
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

        self._store = DataStore(self.cfg.db_url)
        self._spot  = SpotTickCollector(self._api, self.cfg, self._store)
        self._chain = ChainSnapshotCollector(self._api, self.cfg, self._store)
        self._eod   = EODRecorder(self.cfg, self._store)

    def run(self) -> None:
        if self._api is None:
            raise RuntimeError("Call connect() before run().")

        # Register OS signals for clean shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._handle_signal)
            except (OSError, ValueError):
                pass   # not supported on all platforms/threads

        # Start WebSocket spot feed
        self._spot.start()
        log.info("Spot feed started for: %s", ", ".join(self.cfg.symbols))

        # Take first chain snapshot immediately, then every chain_interval_sec
        self._run_chain_snapshot()
        schedule.every(self.cfg.chain_interval_sec).seconds.do(self._run_chain_snapshot)
        log.info("Chain snapshots scheduled every %ds.", self.cfg.chain_interval_sec)

        # Main loop
        log.info("Collector running. Ctrl+C or wait until %s to stop.",
                 self.cfg.shutdown_at)
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

    def _shutdown(self) -> None:
        log.info("Shutting down collector…")
        schedule.clear()
        if self._spot:
            self._spot.stop()
        if not self._eod_done and self._eod:
            try:
                self._eod.record()
            except Exception as exc:
                log.error("EOD record on shutdown failed: %s", exc)
        if self._store:
            self._store.close()
        log.info("Collector shut down cleanly.")
