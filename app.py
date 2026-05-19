"""
app.py — Breeze Trading Dashboard (FastAPI + WebSocket)

Run:   python app.py
Open:  http://localhost:8000
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone, time as _time
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

from trade_engine.chain import OptionChainFetcher
from trade_engine.config import EngineConfig
from trade_engine.engine import OptionsAlgoEngine
from trade_engine.risk import StopLossManager
from trade_engine.router import OrderRouter
from trade_engine.session import BreezeSession
from trade_engine.symbols import SymbolBuilder, nearest_monthly_expiry, nearest_weekly_expiry

from suggestions import SuggestionEngine
from paper_engine import PaperTrader

Path("logs").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)


_LIMITER_STATE_FILE = Path("logs/api_call_count.json")


class BreezeRateLimiter:
    """Thread-safe sliding-window rate limiter for Breeze REST calls.
    Enforces 75 calls/minute and 4,500 calls/day (safe margins below ICICI limits).
    Persists the daily count to disk so server restarts don't reset it to 0."""

    def __init__(self, per_min: int = 75, per_day: int = 4500) -> None:
        self._per_min   = per_min
        self._per_day   = per_day
        self._minute_q  = deque()
        self._day_count = 0
        self._day_date  = date.today()
        self._day_reset = time.monotonic()
        self._lock      = threading.Lock()
        self._dirty     = 0        # calls since last flush
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Resume today's count from disk if the saved date matches today."""
        try:
            data = json.loads(_LIMITER_STATE_FILE.read_text())
            if data.get("date") == str(date.today()):
                self._day_count = int(data.get("count", 0))
        except Exception:
            pass   # first run or corrupt file — start from 0

    def _flush(self) -> None:
        """Write current count to disk (called inside lock, runs in-thread)."""
        try:
            _LIMITER_STATE_FILE.write_text(
                json.dumps({"date": str(self._day_date), "count": self._day_count})
            )
        except Exception:
            pass

    # ── public interface ──────────────────────────────────────────────────────

    def acquire(self, label: str = "api") -> None:
        with self._lock:
            now = time.monotonic()
            # Roll over at midnight
            today = date.today()
            if today != self._day_date:
                self._day_count = 0
                self._day_date  = today
                self._day_reset = now
            while self._minute_q and now - self._minute_q[0] > 60:
                self._minute_q.popleft()
            if len(self._minute_q) >= self._per_min:
                wait = 60 - (now - self._minute_q[0]) + 0.5
                log.warning("Rate limit — waiting %.1fs before %s", wait, label)
                time.sleep(wait)
            if self._day_count >= self._per_day:
                raise RuntimeError(
                    f"Daily Breeze API limit exhausted ({self._day_count} calls used)"
                )
            self._minute_q.append(time.monotonic())
            self._day_count += 1
            self._dirty += 1
            # Flush every 10 calls to balance durability vs I/O
            if self._dirty >= 10:
                self._flush()
                self._dirty = 0
            log.debug("REST [%s] day=%d/%d min=%d/%d",
                      label, self._day_count, self._per_day,
                      len(self._minute_q), self._per_min)

    @property
    def stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            while self._minute_q and now - self._minute_q[0] > 60:
                self._minute_q.popleft()
            return {
                "calls_today":    self._day_count,
                "calls_this_min": len(self._minute_q),
                "day_limit":      self._per_day,
                "min_limit":      self._per_min,
            }

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/dashboard.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("dashboard")
log.setLevel(logging.DEBUG)   # see subscribe/tick diagnostics in logs/dashboard.log

# Silence the Breeze SDK's verbose per-response DEBUG logs
logging.getLogger("APILogger").setLevel(logging.WARNING)

# ── Global state ──────────────────────────────────────────────────────────────

_session:    Optional[BreezeSession]      = None
_algo_engine: Optional[OptionsAlgoEngine] = None
_algo_task:  Optional[asyncio.Task]       = None
_broadcast_task:      Optional[asyncio.Task] = None
_chain_snap_task:     Optional[asyncio.Task] = None   # periodic chain/delta snapshots
_strategy_task:       Optional[asyncio.Task] = None   # strategy signal polling
_candle_flush_task:   Optional[asyncio.Task] = None   # flush live OHLCV to DB every 60 s
_paper_monitor_task:  Optional[asyncio.Task] = None   # auto-exit + periodic P&L push
_trigger_tasks: Dict[str, asyncio.Task]     = {}
_main_loop:  Optional[asyncio.AbstractEventLoop] = None

# ── Strategy runner state ─────────────────────────────────────────────────────
_active_strategies: Dict[str, dict] = {}   # strategy_id -> {instance, cfg, mode, auto_exec}
_strategy_signals: deque = deque(maxlen=500)

_ws_subscriptions: set            = set()
_token_to_symbol:  Dict[str, str] = {}

_positions: List[dict] = []
_order_log: List[dict] = []
_ltp_cache: Dict[str, float] = {}

_tick_log:   Dict[str, deque] = {}
_tick_watch: Optional[str]    = None

_symbol_index: List[dict] = []
_SYMBOL_CACHE  = Path("data/symbols.json")

_limiter = BreezeRateLimiter(per_min=75, per_day=4500)

# ── Live trading safety gate ──────────────────────────────────────────────────
# Default OFF.  Set env var LIVE_TRADING=true (or toggle via /api/settings/live_trading)
# to allow real orders to be sent to Breeze.  Paper trades are always allowed.
_LIVE_TRADING_ENABLED: bool = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"


def _require_live_trading() -> None:
    """Raise 403 if live trading is disabled — call at every real-order entry point."""
    if not _LIVE_TRADING_ENABLED:
        raise HTTPException(
            403,
            "🔒 Live trading is DISABLED. Enable it via POST /api/settings/live_trading "
            "or set LIVE_TRADING=true in your environment and restart.",
        )

# ── Symbol alias map — normalise user-supplied display names to Breeze codes ──
_SYMBOL_ALIASES: Dict[str, str] = {
    # NIFTY variants
    "NIFTY 50":    "NIFTY",
    "NIFTY50":     "NIFTY",
    "CNX NIFTY":   "NIFTY",
    # BANKNIFTY variants
    "BANK NIFTY":  "BANKNIFTY",
    "BANKNIFTY50": "BANKNIFTY",
    "NIFTY BANK":  "BANKNIFTY",
    # FINNIFTY
    "FIN NIFTY":   "FINNIFTY",
    # MIDCPNIFTY
    "MIDCAP NIFTY":"MIDCPNIFTY",
    # Equities — common display names -> Breeze scrip codes
    "RELIANCE":    "RELIND",
    "RELIANCE INDUSTRIES": "RELIND",
    "HDFC BANK":   "HDFBAN",
    "HDFCBANK":    "HDFBAN",
    "HDFC":        "HDFBAN",
    "INFOSYS":     "INFY",
    "STATE BANK":  "SBIN",
    "SBI":         "SBIN",
    "ICICI BANK":  "ICICIBANK",
    "KOTAK BANK":  "KOTAKBANK",
    "BHARTI":      "BHARTIARTL",
    "AIRTEL":      "BHARTIARTL",
    "AXIS BANK":   "AXISBANK",
}

def _normalize_symbol(sym: str) -> str:
    """Resolve display names and aliases to the canonical Breeze trading symbol."""
    s = sym.strip().upper()
    return _SYMBOL_ALIASES.get(s, s)

_MAX_DAILY_LOSS:    float = float(os.getenv("MAX_DAILY_LOSS",    "40000"))
_TOTAL_PREMIUM_CAP: float = float(os.getenv("TOTAL_PREMIUM_CAP", "78000"))

# ── DB store (optional — graceful degradation when PostgreSQL not configured) ──
_db_store = None   # collector.store.DataStore | None

def _build_db_url() -> str:
    """Return DB_URL from env, constructing from parts if DB_URL not set."""
    url = os.getenv("DB_URL", "")
    if url:
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "postgres")
    pwd  = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "trading_data")
    if pwd:
        return f"postgresql://{user}:{pwd}@{host}:{port}/{name}"
    return ""


def _init_db_store() -> None:
    global _db_store
    db_url = _build_db_url()
    if not db_url:
        return
    try:
        from collector.store import DataStore
        _db_store = DataStore(db_url)
        log.info("DB store initialised — ticks and chain snapshots will be persisted.")
    except Exception as exc:
        log.warning("DB store unavailable (PostgreSQL not running?): %s", exc)
        _db_store = None

# ── Spot tick buffer — flushed to DB every 5 s by _tick_writer_thread ─────────
_tick_buffer: List[dict] = []
_tick_buffer_lock = threading.Lock()
_TICK_FLUSH_SEC = 5

# ── Candle write queue — decouples tick handler from DB I/O ──────────────────
# Tick handler puts rows here; _candle_writer_thread drains and batch-inserts.
import queue as _queue
import statistics as _statistics
_candle_write_queue: "_queue.Queue[dict]" = _queue.Queue(maxsize=50_000)

# ── Security master state ────────────────────────────────────────────────────
_sm_running:  bool      = False
_sm_log:      List[str] = []
_sm_status:   dict      = {"status": "idle", "current": "", "error": "", "last_ok": None}
_sm_task                = None  # asyncio Task reference

# ── Historical download state ─────────────────────────────────────────────────
_download_running: bool      = False
_download_log:     List[str] = []
_download_status:  dict      = {
    "status":      "idle",
    "current":     "",
    "error":       "",
    "done_items":  0,
    "total_items": 0,
    "start_ts":    0.0,
    "eta_sec":     None,
}

_DONE_PATTERNS = (
    ": +",       # "Spot NIFTY [1m]: +123 candles."
    "up to date",  # "Spot NIFTY 1m up to date."
)


class _DownloadLogHandler(logging.Handler):
    """Captures log records from the backfill; counts completions for ETA."""
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        _download_log.append(msg)
        if len(_download_log) > 500:
            del _download_log[0]

        # Count one symbol+interval done whenever the backfill logs a result line
        if any(p in msg for p in _DONE_PATTERNS):
            _download_status["done_items"] += 1
            done  = _download_status["done_items"]
            total = _download_status["total_items"]
            elapsed = time.monotonic() - _download_status["start_ts"]
            if done > 0 and elapsed > 0 and total > done:
                rate = done / elapsed           # items per second
                _download_status["eta_sec"] = int((total - done) / rate)
            else:
                _download_status["eta_sec"] = None
            _download_status["current"] = msg.split(" — ")[-1].strip()

WATCHLIST = [
    {"stock": "NIFTY",    "exchange": "NSE", "label": "NIFTY 50"},
    {"stock": "CNXBAN",   "exchange": "NSE", "label": "BANK NIFTY"},   # Breeze NSE cash code for Bank Nifty
    {"stock": "RELIND",   "exchange": "NSE", "label": "RELIANCE"},
    {"stock": "HDFCBANK", "exchange": "NSE", "label": "HDFC BANK"},
    {"stock": "TCS",      "exchange": "NSE", "label": "TCS"},
]

_SYMBOL_EXCHANGE: Dict[str, str] = {w["stock"]: w["exchange"] for w in WATCHLIST}

# ── Market hours (IST) ────────────────────────────────────────────────────────
_IST           = timezone(timedelta(hours=5, minutes=30))
_MARKET_OPEN   = _time(9, 15)
_MARKET_CLOSE  = _time(15, 31)
_SCAN_INTERVAL = int(os.getenv("INTRADAY_SCAN_SEC", "60"))

_intraday_scan_cache: dict = {}    # last server-side scan payload (broadcast to UI)
_intraday_monitor_task = None      # asyncio.Task handle


def _now_ist() -> datetime:
    return datetime.now(tz=_IST)


def _is_market_hours() -> bool:
    t = _now_ist().time()
    return _MARKET_OPEN <= t <= _MARKET_CLOSE

# ── Live candle accumulator (tick -> OHLCV, written to 'candles' table) ────────
# Intervals to build in-process (minutes -> DB label)
_CANDLE_IVLS: Dict[int, str] = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 1440: "1d"}

# {symbol: {interval_min: {ts, open, high, low, close, volume}}}
_live_candles: Dict[str, Dict[int, dict]] = {}
_live_candles_lock = threading.Lock()


def _update_live_candle(symbol: str, ltp: float, volume: int, ts: datetime) -> None:
    """Update per-symbol OHLCV buckets from every tick.
    Closed candles are queued for immediate DB write.
    Partial candles are queued by the candle writer thread every second.
    The tick handler never blocks on DB I/O."""
    ts_epoch = int(ts.timestamp())

    for iMin, label in _CANDLE_IVLS.items():
        bucket_epoch = (ts_epoch // (iMin * 60)) * (iMin * 60)
        bucket_dt    = datetime.fromtimestamp(bucket_epoch)

        with _live_candles_lock:
            sym_ivl = _live_candles.setdefault(symbol, {})
            cur     = sym_ivl.get(iMin)

            if cur is None:
                sym_ivl[iMin] = dict(ts=bucket_dt, open=ltp, high=ltp,
                                     low=ltp, close=ltp, volume=volume)
            elif cur["ts"] == bucket_dt:
                cur["high"]    = max(cur["high"], ltp)
                cur["low"]     = min(cur["low"],  ltp)
                cur["close"]   = ltp
                cur["volume"] += volume
            else:
                # Bucket closed — enqueue immediately (non-blocking)
                try:
                    _candle_write_queue.put_nowait(dict(
                        ts=cur["ts"], symbol=symbol, interval=label,
                        open=cur["open"], high=cur["high"],
                        low=cur["low"],   close=cur["close"],
                        volume=cur["volume"],
                    ))
                except _queue.Full:
                    pass  # circuit-breaker: drop if queue saturated
                sym_ivl[iMin] = dict(ts=bucket_dt, open=ltp, high=ltp,
                                     low=ltp, close=ltp, volume=volume)

_ws_clients: Set[WebSocket] = set()
_suggestion_engine: Optional[SuggestionEngine] = None

_research_calls: List[dict] = []   # manually entered ICICI Direct research calls
_research_seq = 0

_paper: PaperTrader = PaperTrader(starting_capital=1_000_000.0)


# ── Pydantic models ───────────────────────────────────────────────────────────

class ConnectReq(BaseModel):
    api_key:       str
    api_secret:    str
    session_token: str


class ManualOrderReq(BaseModel):
    stock_code:    str
    exchange_code: str           = "NFO"
    product:       str           = "options"   # options | cash
    right:         Optional[str] = None        # CE | PE (options only)
    strike:        Optional[int] = None
    expiry:        Optional[str] = None        # YYYY-MM-DD
    action:        str           = "buy"       # buy | sell
    quantity:      int           = 75
    order_type:    str           = "market"    # market | limit
    price:         float         = 0.0


class TriggerOrderReq(BaseModel):
    watch_stock:        str
    watch_exchange:     str   = "NSE"
    trigger_price:      float
    trigger_direction:  str               # "above" | "below"
    order:              ManualOrderReq
    time_limit_minutes: int   = 60


class AlgoStartReq(BaseModel):
    strategy:    str   = "bull_put_spread"  # bull_put_spread | iron_condor
    expiry_type: str   = "weekly"
    underlying:  str   = "NIFTY"
    num_lots:    int   = 1
    lot_size:    int   = 75
    spread_width: int  = 100
    delta:       float = 0.25
    min_iv_rank: float = 40.0


# ── WebSocket broadcast ───────────────────────────────────────────────────────

async def broadcast(msg: dict) -> None:
    dead = set()
    payload = json.dumps(msg)
    for ws in list(_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


# ── P&L computation ───────────────────────────────────────────────────────────

def _compute_pnl() -> dict:
    total_pnl = 0.0
    deployed  = 0.0
    enriched  = []
    for pos in _positions:
        if not pos.get("is_open"):
            continue
        ltp = _ltp_cache.get(pos["symbol"], pos["entry_price"])
        qty = pos["qty"]
        ep  = pos["entry_price"]
        if pos["action"] == "buy":
            pnl = (ltp - ep) * qty
            deployed += ep * qty
        else:
            pnl = (ep - ltp) * qty
        total_pnl += pnl
        enriched.append({**pos, "ltp": round(ltp, 2), "pnl": round(pnl, 2)})
    return {
        "total_pnl":        round(total_pnl, 2),
        "premium_deployed": round(deployed,   2),
        "premium_cap":      _TOTAL_PREMIUM_CAP,
        "daily_stop":       _MAX_DAILY_LOSS,
        "positions":        enriched,
    }


# ── Breeze WebSocket feed ─────────────────────────────────────────────────────

def _on_tick(tick: dict) -> None:
    """Synchronous callback invoked by the Breeze SDK on every market tick.
    Runs in the SDK's socketio background thread — dict writes are GIL-safe."""
    token = tick.get("symbol", "")
    ltp   = tick.get("last")
    if not token:
        return
    if token not in _token_to_symbol:
        log.debug("Tick for unknown token %s (ltp=%s) — not in token map. Map: %s",
                  token, ltp, list(_token_to_symbol.keys())[:10])
        return
    if ltp is None:
        return

    cache_key = _token_to_symbol[token]
    ltp_f     = float(ltp)
    _ltp_cache[cache_key] = ltp_f   # always update — feeds live UI even outside hours

    now     = datetime.now()
    now_ist = now.astimezone(_IST).time() if now.tzinfo else _now_ist().time()
    in_market_hours = _MARKET_OPEN <= now_ist <= _MARKET_CLOSE

    # ── Buffer tick for DB persistence — only during market hours ─────────────
    # Outside 9:15–15:31 IST the broker may send heartbeat / pre-market ticks;
    # writing those to DB and building candles from them is wasteful.
    tick_vol = int(tick.get("ltq", 0) or 0)
    if _db_store is not None and in_market_hours:
        with _tick_buffer_lock:
            _tick_buffer.append({
                "ts":     now,
                "symbol": cache_key,
                "ltp":    ltp_f,
                "volume": tick_vol,
            })
        # Build live OHLCV candles (1m, 5m, 30m) and flush closed ones to DB
        _update_live_candle(cache_key, ltp_f, tick_vol, now)

    # ── Build tick entry for the live tick pane ───────────────────────────────
    entry = {
        "t":      now.strftime("%H:%M:%S"),
        "ltp":    ltp_f,
        "change": float(tick.get("change", 0) or 0),
        "bid":    float(tick.get("bPrice", 0) or 0),
        "ask":    float(tick.get("sPrice", 0) or 0),
        "ltq":    tick_vol,
        "oi":     int(tick.get("OI", 0) or 0),
    }
    if cache_key not in _tick_log:
        _tick_log[cache_key] = deque(maxlen=200)
    _tick_log[cache_key].appendleft(entry)

    if cache_key == _tick_watch and _main_loop:
        asyncio.run_coroutine_threadsafe(
            broadcast({"type": "tick", "symbol": cache_key, "data": entry}),
            _main_loop,
        )


def _tick_writer_thread() -> None:
    """Background daemon: flush buffered ticks to PostgreSQL every 5 seconds."""
    while True:
        time.sleep(_TICK_FLUSH_SEC)
        if _db_store is None:
            continue
        with _tick_buffer_lock:
            if not _tick_buffer:
                continue
            batch = list(_tick_buffer)
            _tick_buffer.clear()
        try:
            _db_store.insert_spot_ticks(batch)
            log.debug("Flushed %d spot ticks to DB.", len(batch))
        except Exception as exc:
            log.warning("Tick DB flush failed: %s", exc)


def _ws_subscribe(stock: str, exchange: str, product: str = "cash",
                  right: str = "", strike: str = "", expiry: str = "",
                  cache_key: str = "") -> bool:
    """Subscribe to a Breeze WS feed and map the actual tick token to cache_key.

    The subscribe_feeds() response only echoes the stock_code, NOT the internal
    tick token (e.g. "4.1!12345"). We call get_stock_token_value() first to
    obtain that token so _on_tick can look it up in _token_to_symbol.
    """
    sub_key = f"{stock}|{exchange}|{product}|{right}|{strike}|{expiry}"
    if sub_key in _ws_subscriptions or not (_session and _session._api):
        return True   # already subscribed or no session
    try:
        # get_stock_token_value reads self.interval which is only set after the
        # first subscribe_feeds() call. Ensure it exists before calling directly.
        if not hasattr(_session.api, "interval"):
            _session.api.interval = ""

        # Resolve the actual tick token that Breeze will stamp on each tick.
        # get_stock_token_value returns ("4.1!12345", False) on success,
        # or an Exception object (not raised) when the symbol isn't found.
        token_result = _session.api.get_stock_token_value(
            exchange_code=exchange,
            stock_code=stock,
            product_type=product,
            expiry_date=expiry,
            strike_price=str(strike) if strike else "",
            right=right,
            get_exchange_quotes=True,
            get_market_depth=False,
        )
        if isinstance(token_result, Exception):
            log.error("Token lookup failed for %s/%s: %s", stock, exchange, token_result)
            return False
        if not isinstance(token_result, (tuple, list)) or len(token_result) < 2:
            log.error("Unexpected token response for %s/%s: %r", stock, exchange, token_result)
            return False
        eq_token, _ = token_result
        if not eq_token or not isinstance(eq_token, str) or "False" in eq_token:
            log.error("No valid token for %s/%s (token=%r) — symbol may not exist in Breeze master",
                      stock, exchange, eq_token)
            return False

        # Subscribe via WebSocket
        resp = _session.api.subscribe_feeds(
            stock_code=stock,
            exchange_code=exchange,
            product_type=product,
            expiry_date=expiry,
            strike_price=str(strike) if strike else "",
            right=right,
            get_exchange_quotes=True,
            get_market_depth=False,
        )
        log.debug("subscribe_feeds response for %s: %s", stock, resp)

        # Store token -> cache_key mapping so _on_tick can route ticks correctly
        _token_to_symbol[eq_token] = cache_key or stock
        _ws_subscriptions.add(sub_key)
        log.info("WS subscribed: %s -> token %s", cache_key or stock, eq_token)
        return True
    except Exception as exc:
        log.error("WS subscribe failed for %s/%s: %s", stock, exchange, exc)
        return False


def _ws_unsubscribe(stock: str, exchange: str, product: str = "cash",
                    right: str = "", strike: str = "", expiry: str = "") -> None:
    """Unsubscribe from a Breeze feed."""
    sub_key = f"{stock}|{exchange}|{product}|{right}|{strike}|{expiry}"
    if sub_key not in _ws_subscriptions or not (_session and _session._api):
        return
    try:
        _session.api.unsubscribe_feeds(
            stock_code=stock,
            exchange_code=exchange,
            product_type=product,
            expiry_date=expiry,
            strike_price=str(strike) if strike else "",
            right=right,
        )
        _ws_subscriptions.discard(sub_key)
        log.info("WS unsubscribed: %s", stock)
    except Exception as exc:
        log.warning("WS unsubscribe failed for %s: %s", stock, exc)


def _setup_ws_feeds() -> None:
    """Open Breeze WebSocket and subscribe option legs for open positions.
    Watchlist prices come from REST (Update button) + DB seed — not WS.
    Must be called in a thread (blocking SDK calls)."""
    _session.api.on_ticks = _on_tick
    _session.api.ws_connect()
    for pos in _positions:
        if pos.get("is_open") and pos.get("right"):
            expiry_str = SymbolBuilder.breeze_dt(date.fromisoformat(pos["expiry"]))
            right_str  = "call" if pos["right"] == "CE" else "put"
            _ws_subscribe(
                pos["stock"], pos["exchange"], "options",
                right_str, str(pos["strike"]), expiry_str,
                cache_key=pos["symbol"],
            )
    log.info("Breeze WS feeds active — subscribed %d symbols.", len(_ws_subscriptions))


async def _broadcast_loop() -> None:
    """Push LTP + P&L snapshots to all UI clients every second.
    Also broadcasts quota stats every 10 seconds."""
    _tick = 0
    while True:
        await asyncio.sleep(1)
        _tick += 1
        if not _ltp_cache:
            continue
        pnl_data = _compute_pnl()
        await broadcast({"type": "ltp", "data": _ltp_cache.copy()})
        await broadcast({"type": "pnl", "data": pnl_data})
        if _tick % 10 == 0:
            await broadcast({"type": "quota", "data": _limiter.stats})
        if pnl_data["total_pnl"] < -(_MAX_DAILY_LOSS * 0.80):
            await broadcast({
                "type":    "alert",
                "message": (
                    f"⚠ Daily loss ₹{abs(pnl_data['total_pnl']):,.0f} "
                    f"approaching limit ₹{_MAX_DAILY_LOSS:,.0f}"
                ),
            })
        # Strategy auto-exits (capital-preservation: SL 1×credit / target 40%)
        if _tick % 5 == 0:
            strat_exits = _paper.check_strategy_auto_exits(_ltp_cache)
            for ev in strat_exits:
                await broadcast(ev)
            # Alert-only checks for thresholds not yet triggering auto-exit
            alerts = _paper.check_alerts(_ltp_cache)
            for a in alerts:
                await broadcast({"type": "strategy_alert", "alert": a})


# ── Symbol index ──────────────────────────────────────────────────────────────

# Exchange index within token_script_dict_list
_EXCH_IDX = {0: "BSE", 1: "NSE", 2: "NDX", 3: "MCX", 4: "NFO", 5: "BFO"}


def _build_symbol_index() -> None:
    """Extract symbols from the SDK's in-memory security master.

    NSE/BSE equity  -> one entry per stock_code, token preserved.
    NFO/BFO/MCX/NDX -> deduplicated to one entry per (underlying, exchange, product_type)
                       so the dropdown shows 'RELIANCE Futures (NFO)' instead of
                       thousands of individual strike/expiry contracts.
    """
    global _symbol_index
    if not (_session and _session._api):
        return

    entries: List[dict] = []
    seen_derivatives: set = set()

    for idx, exchange in _EXCH_IDX.items():
        try:
            token_dict = _session.api.token_script_dict_list[idx]
        except (IndexError, AttributeError):
            continue

        for token, parts in token_dict.items():
            if not parts:
                continue
            stock_code   = (parts[0] if len(parts) > 0 else "").strip()
            company_name = (parts[1] if len(parts) > 1 else "").strip()
            if not stock_code:
                continue

            if exchange in ("NFO", "BFO", "MCX", "NDX"):
                # Contract format: "FUT-UNDERLYING-EXPIRY" or "OPT-UNDERLYING-EXPIRY-STRIKE-CE/PE"
                segs = stock_code.split("-", 2)
                prod_tag   = segs[0] if len(segs) >= 1 else "?"
                underlying = segs[1] if len(segs) >= 2 else stock_code
                prod_label = "Futures" if prod_tag == "FUT" else "Options" if prod_tag == "OPT" else prod_tag

                key = (underlying, exchange, prod_tag)
                if key in seen_derivatives:
                    continue
                seen_derivatives.add(key)

                entries.append({
                    "stock_code":   underlying,
                    "company_name": company_name or underlying,
                    "token":        "",
                    "exchange":     exchange,
                    "product_type": prod_label,
                })
            else:
                entries.append({
                    "stock_code":   stock_code,
                    "company_name": company_name,
                    "token":        token,
                    "exchange":     exchange,
                    "product_type": "Equity",
                })

    _symbol_index = entries
    log.info("Symbol index built: %d entries (%d derivative underlyings).",
             len(entries), len(seen_derivatives))
    try:
        _SYMBOL_CACHE.parent.mkdir(exist_ok=True)
        with open(_SYMBOL_CACHE, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        log.info("Symbol index saved -> %s", _SYMBOL_CACHE)
    except Exception as exc:
        log.warning("Could not save symbol index: %s", exc)


def _load_symbol_index() -> None:
    """Load the persisted symbol index from disk (survives server restarts)."""
    global _symbol_index
    if not _SYMBOL_CACHE.exists():
        return
    try:
        with open(_SYMBOL_CACHE, encoding="utf-8") as f:
            _symbol_index = json.load(f)
        log.info("Symbol index loaded from disk: %d symbols.", len(_symbol_index))
    except Exception as exc:
        log.warning("Could not load symbol index: %s", exc)


# ── Periodic chain/delta snapshot (runs when connected, stores to DB) ─────────

_CHAIN_SNAP_INTERVAL_SEC = int(os.getenv("CHAIN_SNAP_SEC", "300"))  # default 5 min


def _is_market_hours() -> bool:
    """True only during NSE trading hours: Mon–Fri, 09:00–15:35 IST."""
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    if now.weekday() >= 5:       # Saturday=5, Sunday=6
        return False
    hm = now.hour * 100 + now.minute
    return 900 <= hm <= 1535


async def _chain_snapshot_loop() -> None:
    """Every CHAIN_SNAP_SEC, fetch full option chains + PCR and persist to DB.
    Skipped entirely outside NSE market hours to avoid burning Breeze quota."""
    await asyncio.sleep(60)   # give connection 60 s to settle before first run
    while True:
        if not _is_market_hours():
            log.debug("Chain snapshot skipped — outside market hours.")
            await asyncio.sleep(_CHAIN_SNAP_INTERVAL_SEC)
            continue
        if _session and _session._api and _db_store:
            try:
                from collector.chain import ChainSnapshotCollector
                from collector.config import CollectorConfig
                cfg = CollectorConfig(
                    api_key=_session.cfg.api_key,
                    api_secret=_session.cfg.api_secret,
                    session_token=_session.cfg.session_token,
                    db_url=os.getenv("DB_URL", ""),
                )
                collector = ChainSnapshotCollector(_session.api, cfg, _db_store)
                await asyncio.to_thread(collector.run_once)
                log.info("Chain + PCR snapshot stored to DB.")
            except Exception as exc:
                log.warning("Chain snapshot error: %s", exc)
        await asyncio.sleep(_CHAIN_SNAP_INTERVAL_SEC)


_STRATEGY_POLL_SEC = 10   # generate signals every 10 s

async def _strategy_signal_loop() -> None:
    """Poll all active strategies every 10 s, broadcast signals via WebSocket."""
    await asyncio.sleep(5)   # brief startup delay
    while True:
        for strat_id, run in list(_active_strategies.items()):
            try:
                instance = run["instance"]
                signals  = await asyncio.to_thread(
                    instance.generate_signals,
                    _session, _ltp_cache, _db_store,
                )
                for sig in signals:
                    d = sig.to_dict()
                    _strategy_signals.appendleft(d)
                    await broadcast({"type": "strategy_signal", "signal": d})
                    log.info("Strategy signal [%s] %s %s — %s",
                             strat_id, sig.action, sig.symbol, sig.rationale[:60])

                    if run.get("auto_exec") and run.get("mode") == "paper":
                        _auto_paper_trade(sig)

            except Exception as exc:
                log.warning("Strategy %s error: %s", strat_id, exc)

        await asyncio.sleep(_STRATEGY_POLL_SEC)


def _auto_paper_trade(sig) -> None:
    """Execute a BUY_CALL / BUY_PUT signal as a paper trade."""
    try:
        if sig.action not in ("BUY_CALL", "BUY_PUT"):
            return
        ltp = _ltp_cache.get(sig.symbol, 100.0)
        right = "CE" if sig.action == "BUY_CALL" else "PE"
        symbol = f"{sig.symbol} ATM {right}"
        _paper.open_position(symbol=symbol, entry_price=ltp, qty=75,
                             action="buy", product="options")
        log.info("Auto paper trade: %s %s @ %.2f", sig.action, sig.symbol, ltp)
    except Exception as exc:
        log.debug("Auto paper trade failed: %s", exc)


async def _intraday_monitor_loop() -> None:
    """
    Server-side intraday signal monitor.

    At 9:14:50 IST: auto-subscribes all WATCHLIST symbols via Breeze WebSocket
    (if session is connected). Broadcasts a 'market_open' event to all UIs.

    During 9:15–15:31 IST: evaluates all 5 intraday strategies for WATCHLIST
    every INTRADAY_SCAN_SEC seconds. Stores result in _intraday_scan_cache and
    broadcasts 'intraday_signals' to all connected UIs so the monitor table
    updates without user interaction.

    After 15:31: sleeps until 9:14:50 the next calendar day.
    """
    global _intraday_scan_cache
    log.info("Intraday monitor loop started (scan every %d s).", _SCAN_INTERVAL)
    _announced_open = False

    while True:
        now = _now_ist()
        t   = now.time()

        # ── Before 9:14:50: sleep until then ──────────────────────────────
        pre_open = _time(9, 14, 50)
        if t < pre_open:
            wake_at  = datetime.combine(now.date(), pre_open, tzinfo=_IST)
            sleep_s  = (wake_at - now).total_seconds()
            log.info("Market opens in %.0f s — intraday monitor sleeping.", sleep_s)
            _announced_open = False
            await asyncio.sleep(max(sleep_s, 1))
            continue

        # ── After 15:31: sleep until next day 9:14:50 ─────────────────────
        if t > _MARKET_CLOSE:
            tomorrow = now.date() + timedelta(days=1)
            wake_at  = datetime.combine(tomorrow, pre_open, tzinfo=_IST)
            sleep_s  = (wake_at - now).total_seconds()
            log.info("Market closed — intraday monitor sleeping %.0f s.", sleep_s)
            _announced_open = False
            await asyncio.sleep(max(sleep_s, 1))
            continue

        # ── Market-open announcement (once per day, at 9:15 exactly) ───────
        if not _announced_open and t >= _MARKET_OPEN:
            await broadcast({
                "type":     "market_open",
                "time":     now.strftime("%H:%M:%S"),
                "watchlist": [w["stock"] for w in WATCHLIST],
            })
            _announced_open = True

        # ── Scan all strategies (equity + options) for all watchlist symbols ─
        if t >= _MARKET_OPEN:
            try:
                sym_list = [w["stock"] for w in WATCHLIST]
                payload  = await _run_scan(sym_list)
                payload["source"] = "server"
                _intraday_scan_cache.update(payload)
                await broadcast({"type": "intraday_signals", **payload})

                actionable = payload.get("actionable", 0)
                if actionable:
                    log.info("Intraday scan [%s]: %d signal(s) — %s",
                             payload["scanned_at"], actionable,
                             ", ".join(
                                 f"{r['symbol']}:{r['signal']}:{r['strategy']}"
                                 for r in payload["results"]
                                 if r.get("signal") in ("LONG", "SHORT"))[:6])

            except Exception as exc:
                log.warning("Intraday monitor scan error: %s", exc)

        await asyncio.sleep(_SCAN_INTERVAL)


def _candle_writer_thread() -> None:
    """Dedicated DB writer: drains _candle_write_queue every second.
    Also snapshots all partial candles once per second so charts stay live.
    Runs in its own daemon thread — never blocks the event loop or tick handler."""
    while True:
        time.sleep(1)
        if _db_store is None:
            continue

        # Drain queued closed candles (non-blocking)
        batch: list = []
        while True:
            try:
                batch.append(_candle_write_queue.get_nowait())
            except _queue.Empty:
                break

        # Snapshot all currently-open partial candles
        with _live_candles_lock:
            for symbol, ivls in _live_candles.items():
                for iMin, cur in ivls.items():
                    batch.append(dict(
                        ts=cur["ts"], symbol=symbol,
                        interval=_CANDLE_IVLS[iMin],
                        open=cur["open"], high=cur["high"],
                        low=cur["low"],   close=cur["close"],
                        volume=cur["volume"],
                    ))

        if batch:
            try:
                _db_store.insert_candles(batch)
            except Exception as exc:
                log.warning("Candle writer error: %s", exc)


async def _candle_flush_loop() -> None:
    """Kept for compatibility — actual work is done by _candle_writer_thread."""
    while True:
        await asyncio.sleep(3600)


# ── Paper trading monitor loop ────────────────────────────────────────────────

_PAPER_MONITOR_SEC = 3    # check SL/T1/T2 every 3 seconds
_PAPER_PNL_SEC     = 5    # push P&L update every 5 seconds


async def _paper_monitor_loop() -> None:
    """
    Runs every 3 s (always, not just market hours):
      1. Builds an effective LTP cache: live WebSocket prices first, then DB
         close fallback for any open-position symbol that has no live price.
         This ensures SL/T1/T2 auto-exits fire even when Breeze is offline.
      2. Calls paper_engine.check_auto_exits() — fires SL/T1/T2 auto-exits
         and daily-cap enforcement; broadcasts alerts for each event.
      3. Every 5 s pushes a 'paper_pnl' WebSocket event so the Live P&L pane
         updates even when no order has been placed.
    """
    import time as _time_mod
    _last_pnl_push = 0.0
    while True:
        await asyncio.sleep(_PAPER_MONITOR_SEC)
        try:
            # Build effective LTP: live cache + DB fallback for open positions
            eff_ltp: Dict[str, float] = dict(_ltp_cache)
            open_syms = [p.symbol for p in _paper._positions if p.is_open
                         if p.symbol not in eff_ltp]
            if open_syms and _db_store:
                for sym in open_syms:
                    fb = await asyncio.to_thread(_db_ltp_fallback, sym)
                    if fb:
                        eff_ltp[sym] = fb
                        log.debug("Paper monitor: DB LTP fallback %s=%.2f", sym, fb)

            # Auto-exit check using effective prices
            events = _paper.check_auto_exits(eff_ltp)
            if events:
                summary = _paper.summary(eff_ltp)
                for ev in events:
                    await broadcast({
                        "type":    "paper_auto_exit",
                        "event":   ev,
                        "summary": summary,
                    })
                await broadcast({"type": "paper_update", "data": summary})

            # Periodic P&L push (every _PAPER_PNL_SEC)
            now = _time_mod.monotonic()
            if now - _last_pnl_push >= _PAPER_PNL_SEC:
                _last_pnl_push = now
                summary = _paper.summary(eff_ltp)
                await broadcast({"type": "paper_pnl", "data": summary})
        except Exception as exc:
            log.debug("Paper monitor loop error: %s", exc)


# ── App lifespan ──────────────────────────────────────────────────────────────

async def _security_master_loop() -> None:
    """
    Downloads the ICICI Direct security master daily at 08:30 IST (03:00 UTC).
    On first start, runs immediately if today's data hasn't been fetched yet.
    """
    global _sm_running, _sm_log, _sm_status

    IST_OFFSET = 5 * 3600 + 30 * 60  # UTC+5:30 in seconds
    TARGET_IST_HOUR, TARGET_IST_MIN = 8, 30  # 08:30 IST

    def _seconds_until_next_run() -> float:
        now_utc = datetime.now(timezone.utc)
        now_ist_ts = now_utc.timestamp() + IST_OFFSET
        now_ist = datetime.utcfromtimestamp(now_ist_ts)
        # Next 08:30 IST in UTC
        target_ist = now_ist.replace(hour=TARGET_IST_HOUR, minute=TARGET_IST_MIN, second=0, microsecond=0)
        if now_ist >= target_ist:
            target_ist = target_ist.replace(day=target_ist.day + 1)
        return (target_ist - now_ist).total_seconds()

    def _run_sm():
        global _sm_running, _sm_status
        from collector.security_master import SecurityMasterDownloader
        db_url = os.environ.get("DB_URL", "")
        if not db_url or not _db_store:
            _sm_status.update(status="error", error="DB not configured", current="")
            return
        _sm_running = True
        _sm_log.clear()
        _sm_status.update(status="running", error="", current="Starting…")
        try:
            def _cb(msg: str):
                _sm_log.append(msg)
                if len(_sm_log) > 200:
                    del _sm_log[0]
                _sm_status["current"] = msg[:120]
            SecurityMasterDownloader(db_url=db_url, progress_cb=_cb).run()
            _sm_status.update(status="complete", current="Done",
                              last_ok=datetime.now().isoformat(timespec="seconds"), error="")
        except Exception as exc:
            log.error("Security master refresh failed: %s", exc)
            _sm_status.update(status="error", current="", error=str(exc))
        finally:
            _sm_running = False

    # Run immediately on startup if no data yet
    if _db_store:
        try:
            stats = _db_store.security_master_stats()
            if stats.get("total", 0) == 0:
                log.info("Security master table empty — running initial download.")
                await asyncio.to_thread(_run_sm)
        except Exception:
            pass

    while True:
        wait = _seconds_until_next_run()
        log.info("Security master: next refresh in %.0f min (08:30 IST).", wait / 60)
        await asyncio.sleep(wait)
        if not _sm_running:
            await asyncio.to_thread(_run_sm)


async def _auto_connect_breeze(api_key: str, api_secret: str, session_token: str) -> None:
    """Auto-connect Breeze session from .env credentials at startup."""
    global _session, _suggestion_engine
    await asyncio.sleep(1)   # let the server finish binding before connecting
    if _session and _session._api:
        return
    try:
        cfg = EngineConfig(api_key=api_key, api_secret=api_secret, session_token=session_token)
        _session = BreezeSession(cfg)
        await asyncio.to_thread(_session.connect)
        await asyncio.to_thread(_setup_ws_feeds)
        await asyncio.to_thread(_build_symbol_index)
        _suggestion_engine = SuggestionEngine(_ltp_cache)
        await broadcast({"type": "status", "connected": True})
        log.info("Breeze auto-connected from .env credentials.")
    except Exception as exc:
        _session = None
        log.warning("Breeze auto-connect failed (bad session token?): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcast_task, _chain_snap_task, _strategy_task, _main_loop
    global _candle_flush_task, _intraday_monitor_task, _paper_monitor_task, _sm_task
    _main_loop              = asyncio.get_event_loop()
    _broadcast_task         = asyncio.create_task(_broadcast_loop())
    _chain_snap_task        = asyncio.create_task(_chain_snapshot_loop())
    _strategy_task          = asyncio.create_task(_strategy_signal_loop())
    _candle_flush_task      = asyncio.create_task(_candle_flush_loop())
    _intraday_monitor_task  = asyncio.create_task(_intraday_monitor_loop())
    _paper_monitor_task     = asyncio.create_task(_paper_monitor_loop())
    _load_symbol_index()
    _init_db_store()   # connect to PostgreSQL if DB_URL is set
    if _db_store:
        try:
            _db_store.ensure_watchlist_state_table()
        except Exception as _e:
            log.warning("watchlist_state table init failed: %s", _e)
    _sm_task                = asyncio.create_task(_security_master_loop())
    # Start background writer threads (no-op if DB unavailable)
    threading.Thread(target=_tick_writer_thread,   daemon=True, name="tick-writer").start()
    threading.Thread(target=_candle_writer_thread, daemon=True, name="candle-writer").start()
    # Auto-connect Breeze if all credentials are present in .env
    _env_key   = os.getenv("BREEZE_API_KEY", "")
    _env_sec   = os.getenv("BREEZE_API_SECRET", "")
    _env_tok   = os.getenv("BREEZE_SESSION_TOKEN", "")
    if _env_key and _env_sec and _env_tok:
        asyncio.create_task(_auto_connect_breeze(_env_key, _env_sec, _env_tok))
    log.info("Dashboard running -> http://localhost:8000")
    yield
    if _broadcast_task:
        _broadcast_task.cancel()
    if _chain_snap_task:
        _chain_snap_task.cancel()
    if _strategy_task:
        _strategy_task.cancel()
    if _candle_flush_task:
        _candle_flush_task.cancel()
    if _intraday_monitor_task:
        _intraday_monitor_task.cancel()
    if _paper_monitor_task:
        _paper_monitor_task.cancel()
    if _sm_task:
        _sm_task.cancel()
    for t in _trigger_tasks.values():
        t.cancel()
    # Flush remaining buffered ticks before exit
    if _db_store and _tick_buffer:
        with _tick_buffer_lock:
            remaining = list(_tick_buffer)
            _tick_buffer.clear()
        if remaining:
            try:
                _db_store.insert_spot_ticks(remaining)
            except Exception:
                pass
        _db_store.close()
    if _session:
        try:
            await asyncio.to_thread(_session.api.ws_disconnect)
        except Exception:
            pass
        await asyncio.to_thread(_session.disconnect)
    log.info("Dashboard shutdown complete.")


app = FastAPI(title="Breeze Trading Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/live")
async def live_page():
    return FileResponse("static/live.html")


@app.get("/strategies")
async def strategies_page():
    return FileResponse("static/strategies.html")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    log.info("WS client connected (%d total)", len(_ws_clients))
    try:
        await ws.send_text(json.dumps({
            "type":      "init",
            "connected": bool(_session and _session._api),
            "ltp":       _ltp_cache,
            "pnl":       _compute_pnl(),
            "orders":    _order_log[-50:],
        }))
        while True:
            data = await ws.receive_text()   # keep-alive ping
            if data == "ping":
                await ws.send_text('{"type":"pong"}')
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _ws_clients.discard(ws)
        log.info("WS client disconnected (%d remaining)", len(_ws_clients))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_session():
    if not (_session and _session._api):
        raise HTTPException(400, "Not connected — call POST /api/connect first.")


def _record_order(action: str, symbol: str, qty: int, price: float, order_id: str):
    entry = {
        "time":     datetime.now().strftime("%H:%M:%S"),
        "action":   action.upper(),
        "symbol":   symbol,
        "qty":      qty,
        "price":    price,
        "order_id": order_id,
    }
    _order_log.append(entry)
    return entry


# ── Credentials helper ───────────────────────────────────────────────────────

@app.get("/api/credentials")
async def get_credentials():
    """Return credentials from .env for UI pre-fill. Safe on localhost."""
    return {
        "api_key":       os.getenv("BREEZE_API_KEY", ""),
        "api_secret":    os.getenv("BREEZE_API_SECRET", ""),
        "session_token": os.getenv("BREEZE_SESSION_TOKEN", ""),
        "db_url":        os.getenv("DB_URL", ""),
        "db_host":       os.getenv("DB_HOST", "localhost"),
        "db_port":       os.getenv("DB_PORT", "5432"),
        "db_user":       os.getenv("DB_USER", "postgres"),
        "db_password":   os.getenv("DB_PASSWORD", ""),
        "db_name":       os.getenv("DB_NAME", "trading_data"),
    }


# ── Connect / disconnect ──────────────────────────────────────────────────────

@app.post("/api/connect")
async def connect(req: ConnectReq):
    global _session, _suggestion_engine
    if _session and _session._api:
        return {"status": "already_connected"}
    cfg = EngineConfig(
        api_key=req.api_key,
        api_secret=req.api_secret,
        session_token=req.session_token,
    )
    try:
        _session = BreezeSession(cfg)
        await asyncio.to_thread(_session.connect)
        await asyncio.to_thread(_setup_ws_feeds)
        await asyncio.to_thread(_build_symbol_index)   # extract from SDK security master
    except Exception as exc:
        _session = None
        raise HTTPException(500, f"Connection failed: {exc}")
    _suggestion_engine = SuggestionEngine(_ltp_cache)
    await broadcast({"type": "status", "connected": True})
    return {"status": "connected"}


@app.post("/api/disconnect")
async def disconnect_api():
    global _session
    if _session:
        try:
            await asyncio.to_thread(_session.api.ws_disconnect)
        except Exception:
            pass
        _ws_subscriptions.clear()
        _token_to_symbol.clear()
        await asyncio.to_thread(_session.disconnect)
        _session = None
    await broadcast({"type": "status", "connected": False})
    return {"status": "disconnected"}


@app.get("/api/status")
async def get_status():
    rl = _limiter.stats
    return {
        "connected":            bool(_session and _session._api),
        "algo_running":         bool(_algo_task and not _algo_task.done()),
        "live_trading_enabled": _LIVE_TRADING_ENABLED,
        "api_calls_today":      rl["calls_today"],
        "api_calls_min":        rl["calls_this_min"],
        "api_day_limit":        rl["day_limit"],
        "api_min_limit":        rl["min_limit"],
    }


class LiveTradingToggleReq(BaseModel):
    enabled: bool
    confirm: bool = False   # must be True to enable live trading


@app.post("/api/settings/live_trading")
async def set_live_trading(req: LiveTradingToggleReq):
    """
    Enable or disable live order placement.

    Enabling requires confirm=true as an extra safeguard.
    Disabling takes effect immediately — all real-order endpoints return 403.
    """
    global _LIVE_TRADING_ENABLED
    if req.enabled and not req.confirm:
        raise HTTPException(
            400,
            "confirm=true is required to enable live trading. "
            "This will allow REAL orders to be sent to your broker.",
        )
    _LIVE_TRADING_ENABLED = req.enabled
    state = "ENABLED" if req.enabled else "DISABLED"
    log.warning("Live trading %s by user request.", state)
    await broadcast({"type": "live_trading_changed", "enabled": req.enabled})
    return {"live_trading_enabled": _LIVE_TRADING_ENABLED, "status": state}


@app.get("/api/db/status")
async def get_db_status():
    """DB health check — no session required, always available."""
    db_url = os.getenv("DB_URL", "")
    if not db_url:
        return {"available": False, "mode": "memory",
                "reason": "DB_URL not set in .env", "candles_count": 0}
    if _db_store is None:
        return {"available": False, "mode": "memory",
                "reason": "PostgreSQL unreachable (check service + DB_URL)",
                "candles_count": 0}
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM candles")
        candles_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM spot_ticks")
        ticks_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM candles")
        symbols_count = cur.fetchone()[0]
        conn.close()
        return {
            "available":     True,
            "mode":          "db",
            "candles_count": candles_count,
            "ticks_count":   ticks_count,
            "symbols_count": symbols_count,
        }
    except Exception as exc:
        return {"available": False, "mode": "memory",
                "reason": str(exc), "candles_count": 0}


class DbConfigReq(BaseModel):
    host:     str = "localhost"
    port:     int = 5432
    dbname:   str = "trading_data"
    user:     str = "postgres"
    password: str = ""


class WatchlistBackfillReq(BaseModel):
    from_date: Optional[str]       = None   # "YYYY-MM-DD" — defaults to 1 year ago
    to_date:   Optional[str]       = None   # "YYYY-MM-DD" — defaults to today
    symbols:   Optional[List[str]] = None   # if provided, overrides _BACKFILL_PRIORITY


@app.post("/api/db/configure")
async def configure_db(req: DbConfigReq):
    """
    Accept DB connection details from the UI wizard, test the connection,
    run schema setup if tables are missing, and activate the global DataStore.
    """
    global _db_store
    host     = req.host
    port     = req.port
    dbname   = req.dbname
    user     = req.user
    password = req.password

    # Use urllib.parse.quote to handle special chars in URL; also keep kwarg form for connect()
    from urllib.parse import quote_plus
    db_url = f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}"

    try:
        import psycopg2
        # Use keyword args — avoids URL parsing issues with special chars in password
        conn = psycopg2.connect(
            host=host, port=port, dbname=dbname,
            user=user, password=password,
            connect_timeout=5,
        )

        # Auto-create tables if they don't exist yet
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'candles'
        """)
        tables_exist = cur.fetchone()[0] > 0

        if not tables_exist:
            log.info("DB configure: tables not found — running schema setup.")
            import subprocess, sys
            setup_script = Path(__file__).parent / "scripts" / "setup_db.py"
            if setup_script.exists():
                result = subprocess.run(
                    [sys.executable, str(setup_script)],
                    env={**os.environ, "DB_URL": db_url},
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    conn.close()
                    return {"ok": False, "error": f"Schema setup failed: {result.stderr[:400]}"}

        cur.execute("SELECT COUNT(*) FROM candles")
        candles_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM candles")
        symbols_count = cur.fetchone()[0]
        conn.close()

    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Activate global store and persist URL for this process
    os.environ["DB_URL"] = db_url
    try:
        from collector.store import DataStore
        if _db_store is not None:
            try:
                _db_store.close()
            except Exception:
                pass
        _db_store = DataStore(db_url)
        log.info("DB store (re)initialised from UI wizard — %s candles.", candles_count)
    except Exception as exc:
        return {"ok": False, "error": f"DataStore init failed: {exc}"}

    return {"ok": True, "candles_count": candles_count, "symbols_count": symbols_count}


@app.post("/api/db/disable")
async def disable_db():
    """Deactivate the DB store — revert to in-memory mode."""
    global _db_store
    if _db_store is not None:
        try:
            _db_store.close()
        except Exception:
            pass
        _db_store = None
    os.environ.pop("DB_URL", None)
    log.info("DB store disabled by user — running in-memory mode.")
    return {"ok": True}


# ── Manual order ──────────────────────────────────────────────────────────────

@app.post("/api/order/manual")
async def place_manual_order(req: ManualOrderReq):
    _require_session()
    _require_live_trading()

    expiry_obj = date.fromisoformat(req.expiry) if req.expiry else date.today()
    right_str  = ("call" if req.right == "CE" else "put") if req.right else ""

    # SEBI rule: all orders must be LIMIT type.
    # For "market" requests, compute a ±0.5% buffer price from latest LTP.
    symbol_for_ltp = (
        SymbolBuilder.build(req.stock_code, expiry_obj, req.strike, req.right, "monthly")
        if req.product == "options" and req.strike and req.right
        else req.stock_code
    )
    if req.order_type == "market":
        ltp_now = _ltp_cache.get(symbol_for_ltp, _ltp_cache.get(req.stock_code, 0.0))
        if ltp_now <= 0:
            raise HTTPException(
                400,
                "No live LTP available for market-to-limit conversion. "
                "Use a limit order and enter the price manually.",
            )
        buf      = 1.005 if req.action == "buy" else 0.995
        limit_px = round(ltp_now * buf, 2)
    else:
        limit_px = req.price

    kwargs: dict = dict(
        stock_code         = req.stock_code,
        exchange_code      = req.exchange_code,
        product            = req.product,
        action             = req.action,
        order_type         = "limit",   # always limit (SEBI mandate)
        stoploss           = "0",
        quantity           = str(req.quantity),
        price              = str(limit_px),
        validity           = "day",
        validity_date      = SymbolBuilder.breeze_dt(date.today()),
        disclosed_quantity = "0",
    )
    if req.product == "options":
        kwargs.update(
            expiry_date  = SymbolBuilder.breeze_dt(expiry_obj),
            right        = right_str,
            strike_price = str(req.strike or 0),
        )
    else:
        kwargs.update(expiry_date="", right="", strike_price="")

    try:
        await asyncio.to_thread(_limiter.acquire, "place_order")
        resp = await asyncio.to_thread(_session.api.place_order, **kwargs)
    except RuntimeError as exc:
        raise HTTPException(429, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if resp.get("Status") != 200:
        raise HTTPException(400, f"Breeze rejected order: {resp}")

    order_id    = resp["Success"]["order_id"]
    symbol      = symbol_for_ltp   # already computed above
    entry_price = limit_px         # always a limit price

    pos = {
        "symbol":      symbol,
        "stock":       req.stock_code,
        "exchange":    req.exchange_code,
        "product":     req.product,
        "right":       req.right,
        "strike":      req.strike,
        "expiry":      expiry_obj.isoformat() if req.product == "options" else "",
        "action":      req.action,
        "qty":         req.quantity,
        "entry_price": entry_price,
        "order_id":    order_id,
        "is_open":     True,
        "time":        datetime.now().isoformat(),
    }
    _positions.append(pos)

    # Subscribe live feed for option legs so LTP arrives via WebSocket
    if req.product == "options" and req.right and req.strike:
        _ws_subscribe(
            req.stock_code, req.exchange_code, "options",
            right_str, str(req.strike), SymbolBuilder.breeze_dt(expiry_obj),
            cache_key=symbol,
        )

    log_entry = _record_order(req.action, symbol, req.quantity, entry_price, order_id)
    await broadcast({"type": "order", "data": log_entry})
    log.info("Manual order: %s %s ×%d -> %s", req.action.upper(), symbol, req.quantity, order_id)
    return {"status": "placed", "order_id": order_id, "symbol": symbol}


@app.delete("/api/order/{order_id}")
async def cancel_order(order_id: str, exchange_code: str = "NFO"):
    _require_session()
    _require_live_trading()
    await asyncio.to_thread(_limiter.acquire, "cancel_order")
    resp = await asyncio.to_thread(
        _session.api.cancel_order,
        exchange_code=exchange_code,
        order_id=order_id,
    )
    if resp.get("Status") != 200:
        raise HTTPException(400, f"Cancel failed: {resp}")
    return {"status": "cancelled", "order_id": order_id}


# ── Position exit ─────────────────────────────────────────────────────────────

@app.post("/api/position/exit")
async def exit_position(body: dict):
    _require_session()
    order_id = body.get("order_id")
    pos = next((p for p in _positions if p["order_id"] == order_id and p["is_open"]), None)
    if not pos:
        raise HTTPException(404, "Open position not found")

    exit_req = ManualOrderReq(
        stock_code    = pos["stock"],
        exchange_code = pos["exchange"],
        product       = pos["product"],
        right         = pos["right"],
        strike        = pos["strike"],
        expiry        = pos["expiry"] or None,
        action        = "sell" if pos["action"] == "buy" else "buy",
        quantity      = pos["qty"],
        order_type    = "market",
    )
    result = await place_manual_order(exit_req)
    pos["is_open"] = False

    # Unsubscribe the option feed — no open position needs it anymore
    if pos.get("right") and pos.get("strike") and pos.get("expiry"):
        right_str  = "call" if pos["right"] == "CE" else "put"
        expiry_str = SymbolBuilder.breeze_dt(date.fromisoformat(pos["expiry"]))
        _ws_unsubscribe(pos["stock"], pos["exchange"], "options",
                        right_str, str(pos["strike"]), expiry_str)

    await broadcast({"type": "pnl", "data": _compute_pnl()})
    return result


@app.post("/api/position/flatten-all")
async def flatten_all():
    _require_session()
    results = []
    for pos in list(_positions):
        if pos["is_open"]:
            try:
                r = await exit_position({"order_id": pos["order_id"]})
                results.append(r)
            except Exception as exc:
                results.append({"error": str(exc), "order_id": pos["order_id"]})
    return {"flattened": len(results), "results": results}


# ── Trigger order ─────────────────────────────────────────────────────────────

async def _trigger_watcher(key: str, req: TriggerOrderReq) -> None:
    loop      = asyncio.get_event_loop()
    deadline  = loop.time() + req.time_limit_minutes * 60
    direction = req.trigger_direction.lower()
    log.info("Trigger watching %s %s %.2f", req.watch_stock, direction, req.trigger_price)
    try:
        while loop.time() < deadline:
            ltp = _ltp_cache.get(req.watch_stock)
            if ltp is not None:
                fired = (
                    (direction == "above" and ltp >= req.trigger_price) or
                    (direction == "below" and ltp <= req.trigger_price)
                )
                if fired:
                    log.info("Trigger fired: %s %.2f %s %.2f",
                             req.watch_stock, ltp, direction, req.trigger_price)
                    await broadcast({
                        "type":    "alert",
                        "message": (
                            f"TRIGGER FIRED: {req.watch_stock} "
                            f"@ ₹{ltp:,.2f} ({direction} {req.trigger_price:,.2f})"
                        ),
                    })
                    await place_manual_order(req.order)
                    return
            await asyncio.sleep(3)

        await broadcast({
            "type":    "alert",
            "message": (
                f"TRIGGER EXPIRED: {req.watch_stock} never crossed "
                f"₹{req.trigger_price:,.2f} in {req.time_limit_minutes} min"
            ),
        })
    except asyncio.CancelledError:
        pass
    finally:
        _trigger_tasks.pop(key, None)


@app.post("/api/order/trigger")
async def register_trigger(req: TriggerOrderReq):
    _require_session()
    _require_live_trading()
    key  = f"{req.watch_stock}_{req.trigger_direction}_{req.trigger_price}"
    task = asyncio.create_task(_trigger_watcher(key, req))
    _trigger_tasks[key] = task
    return {"status": "registered", "trigger_key": key}


@app.delete("/api/trigger/{key}")
async def cancel_trigger(key: str):
    task = _trigger_tasks.pop(key, None)
    if task:
        task.cancel()
        return {"status": "cancelled"}
    raise HTTPException(404, "Trigger not found")


@app.get("/api/triggers")
async def list_triggers():
    return {"triggers": [k for k, t in _trigger_tasks.items() if not t.done()]}


# ── Algo control ──────────────────────────────────────────────────────────────

@app.post("/api/algo/start")
async def start_algo(req: AlgoStartReq):
    global _algo_engine, _algo_task
    _require_session()
    _require_live_trading()
    if _algo_task and not _algo_task.done():
        return {"status": "already_running"}

    cfg = EngineConfig(
        api_key            = _session.cfg.api_key,
        api_secret         = _session.cfg.api_secret,
        session_token      = _session.cfg.session_token,
        underlying         = req.underlying,
        strategy           = req.strategy,
        expiry_type        = req.expiry_type,
        num_lots           = req.num_lots,
        lot_size           = req.lot_size,
        spread_width       = req.spread_width,
        short_delta_target = req.delta,
        min_iv_rank        = req.min_iv_rank,
    )

    async def _run():
        engine = OptionsAlgoEngine(cfg)
        engine.session = _session
        engine.router  = OrderRouter(_session)
        engine.fetcher = OptionChainFetcher(_session)
        try:
            entered = await asyncio.to_thread(engine.run_entry_scan)
            if entered:
                await broadcast({"type": "alert", "message": f"ALGO: {req.strategy} — position entered"})
                await asyncio.to_thread(engine.run_monitor_loop, 60)
                await broadcast({"type": "alert", "message": f"ALGO: {req.strategy} — monitor loop exited"})
            else:
                await broadcast({"type": "alert", "message": f"ALGO: {req.strategy} — no trade taken"})
        except asyncio.CancelledError:
            if engine.position and engine.position.is_open:
                slm = StopLossManager(_session, engine.router, cfg)
                await asyncio.to_thread(slm.force_flatten, engine.position)
                await broadcast({"type": "alert", "message": "ALGO: force-flattened on stop"})
        except Exception as exc:
            log.error("Algo error: %s", exc, exc_info=True)
            await broadcast({"type": "alert", "message": f"ALGO ERROR: {exc}"})

    _algo_task = asyncio.create_task(_run())
    return {"status": "started", "strategy": req.strategy}


@app.post("/api/algo/stop")
async def stop_algo():
    global _algo_task
    if _algo_task and not _algo_task.done():
        _algo_task.cancel()
        try:
            await _algo_task
        except asyncio.CancelledError:
            pass
    _algo_task = None
    return {"status": "stopped"}


# ── Query endpoints ───────────────────────────────────────────────────────────

@app.get("/api/positions")
async def get_positions():
    return _compute_pnl()


@app.get("/api/orders")
async def get_orders():
    return {"orders": _order_log[-100:]}


@app.get("/api/ltp")
async def get_ltp():
    return _ltp_cache


@app.get("/api/chain")
async def get_chain(stock: str = "NIFTY", expiry_type: str = "weekly"):
    _require_session()
    fetcher = OptionChainFetcher(_session)
    expiry  = nearest_weekly_expiry() if expiry_type == "weekly" else nearest_monthly_expiry()
    chain   = await asyncio.to_thread(fetcher.fetch, expiry)
    return {
        "expiry": expiry.isoformat(),
        "chain":  chain[["strike_price","right","ltp","open_interest","volume"]].to_dict("records"),
    }


# ── Breeze order book & positions ────────────────────────────────────────────

def _breeze_error_msg(resp: Optional[dict]) -> str:
    """Extract a human-readable error from a Breeze API response."""
    if not resp:
        return "No response from Breeze"
    err = resp.get("Error") or ""
    if "Checksum" in err or "Authentication" in err:
        return "Session expired — please Disconnect and reconnect with a fresh session token."
    if "Limit exceed" in err:
        return f"API rate limit hit — try again in a minute. ({err})"
    return err or f"Breeze status {resp.get('Status')}"


@app.get("/api/breeze/orders")
async def get_breeze_orders():
    """Fetch today's full order book from Breeze across NSE + NFO."""
    _require_session()
    today   = datetime.now()
    from_dt = today.strftime("%Y-%m-%dT00:00:00.000Z")
    to_dt   = today.strftime("%Y-%m-%dT23:59:59.000Z")

    all_orders = []
    warning    = None
    for exch in ("NSE", "NFO"):
        try:
            await asyncio.to_thread(_limiter.acquire, f"get_order_list_{exch}")
            resp = await asyncio.to_thread(
                _session.api.get_order_list,
                exchange_code=exch,
                from_date=from_dt,
                to_date=to_dt,
            )
            if resp and resp.get("Status") == 200 and resp.get("Success"):
                for o in resp["Success"]:
                    o["_exchange"] = exch
                    all_orders.append(o)
            elif resp and resp.get("Status") != 200:
                warning = _breeze_error_msg(resp)
                log.warning("Order list %s: %s", exch, warning)
                break   # same auth issue will affect other exchanges too
        except Exception as exc:
            warning = str(exc)
            log.warning("Order list fetch failed for %s: %s", exch, exc)

    return {"orders": all_orders, "count": len(all_orders), "warning": warning}


@app.get("/api/breeze/positions")
async def get_breeze_positions():
    """Fetch current portfolio positions from Breeze."""
    _require_session()
    try:
        await asyncio.to_thread(_limiter.acquire, "get_portfolio_positions")
        resp = await asyncio.to_thread(_session.api.get_portfolio_positions)
    except Exception as exc:
        return {"positions": [], "warning": str(exc)}

    if resp and resp.get("Status") == 200:
        return {"positions": resp.get("Success") or [], "warning": None}
    return {"positions": [], "warning": _breeze_error_msg(resp)}


@app.post("/api/breeze/orders/{order_id}/cancel")
async def cancel_breeze_order(order_id: str, exchange_code: str = "NFO"):
    _require_session()
    await asyncio.to_thread(_limiter.acquire, "cancel_order")
    resp = await asyncio.to_thread(
        _session.api.cancel_order,
        exchange_code=exchange_code,
        order_id=order_id,
    )
    if resp and resp.get("Status") == 200:
        return {"status": "cancelled", "order_id": order_id}
    raise HTTPException(400, f"Cancel failed: {resp}")


# ── Breeze read-only data explorer ───────────────────────────────────────────
# IMPORTANT: All endpoints below are GET-only, purely read/informational.
# NO _require_live_trading() guard — available even when LIVE_TRADING=false.
# Requires only an active Breeze session (_require_session).

@app.get("/api/breeze/funds")
async def get_breeze_funds():
    """Fetch account funds/balance — read-only."""
    _require_session()
    try:
        await asyncio.to_thread(_limiter.acquire, "get_funds")
        resp = await asyncio.to_thread(_session.api.get_funds)
    except Exception as exc:
        return {"funds": None, "warning": str(exc)}
    if resp and resp.get("Status") == 200:
        data = resp.get("Success") or []
        return {"funds": data[0] if isinstance(data, list) and data else data, "warning": None}
    return {"funds": None, "warning": _breeze_error_msg(resp)}


@app.get("/api/breeze/holdings")
async def get_breeze_holdings(exchange_code: str = "NSE"):
    """Fetch portfolio holdings with P&L — read-only."""
    _require_session()
    today   = datetime.now()
    from_dt = today.strftime("%Y-%m-%dT00:00:00.000Z")
    to_dt   = today.strftime("%Y-%m-%dT23:59:59.000Z")
    try:
        await asyncio.to_thread(_limiter.acquire, "get_portfolio_holdings")
        resp = await asyncio.to_thread(
            _session.api.get_portfolio_holdings,
            exchange_code=exchange_code,
            from_date=from_dt,
            to_date=to_dt,
            stock_code="",
            portfolio_type="",
        )
    except Exception as exc:
        return {"holdings": [], "warning": str(exc)}
    if resp and resp.get("Status") == 200:
        return {"holdings": resp.get("Success") or [], "warning": None}
    return {"holdings": [], "warning": _breeze_error_msg(resp)}


@app.get("/api/breeze/demat-holdings")
async def get_breeze_demat_holdings():
    """Fetch demat holdings (stock codes, ISINs, qty) — read-only."""
    _require_session()
    try:
        await asyncio.to_thread(_limiter.acquire, "get_demat_holdings")
        resp = await asyncio.to_thread(_session.api.get_demat_holdings)
    except Exception as exc:
        return {"holdings": [], "warning": str(exc)}
    if resp and resp.get("Status") == 200:
        return {"holdings": resp.get("Success") or [], "warning": None}
    return {"holdings": [], "warning": _breeze_error_msg(resp)}


@app.get("/api/breeze/trades")
async def get_breeze_trades():
    """Fetch today's executed trades (NSE + NFO) — read-only."""
    _require_session()
    today   = datetime.now()
    from_dt = today.strftime("%Y-%m-%dT00:00:00.000Z")
    to_dt   = today.strftime("%Y-%m-%dT23:59:59.000Z")
    all_trades: list = []
    warning: Optional[str] = None
    for exch in ("NSE", "NFO"):
        try:
            await asyncio.to_thread(_limiter.acquire, f"get_trade_list_{exch}")
            resp = await asyncio.to_thread(
                _session.api.get_trade_list,
                from_date=from_dt,
                to_date=to_dt,
                exchange_code=exch,
            )
            if resp and resp.get("Status") == 200 and resp.get("Success"):
                for t in resp["Success"]:
                    t["_exchange"] = exch
                    all_trades.append(t)
            elif resp and resp.get("Status") not in (200, None):
                warning = _breeze_error_msg(resp)
                break
        except Exception as exc:
            warning = str(exc)
    return {"trades": all_trades, "count": len(all_trades), "warning": warning}


@app.get("/api/breeze/margins")
async def get_breeze_margins(exchange_code: str = "NSE"):
    """Fetch margin details for an exchange — read-only."""
    _require_session()
    try:
        await asyncio.to_thread(_limiter.acquire, "get_margin")
        resp = await asyncio.to_thread(
            _session.api.get_margin,
            exchange_code=exchange_code,
        )
    except Exception as exc:
        return {"margins": None, "warning": str(exc)}
    if resp and resp.get("Status") == 200:
        data = resp.get("Success") or []
        return {"margins": data[0] if isinstance(data, list) and data else data, "warning": None}
    return {"margins": None, "warning": _breeze_error_msg(resp)}


_INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "CNXBAN", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}

@app.get("/api/breeze/quote")
async def get_breeze_quote(
    stock_code:    str,
    exchange_code: str = "NSE",
    product_type:  str = "cash",
    expiry_date:   str = "",
    right:         str = "",
    strike_price:  str = "",
):
    """Fetch live quote for any symbol/instrument — read-only.
    For index symbols (BANKNIFTY etc.) that return empty on NSE-cash,
    automatically retries using the nearest weekly futures on NFO."""
    _require_session()

    async def _query(ec, pt, exp="", r="", sp=""):
        await asyncio.to_thread(_limiter.acquire, "get_quotes")
        return await asyncio.to_thread(
            _session.api.get_quotes,
            stock_code=stock_code.upper(),
            exchange_code=ec,
            expiry_date=exp,
            product_type=pt,
            right=r,
            strike_price=sp,
        )

    # ── Primary attempt ───────────────────────────────────────────────
    try:
        resp = await _query(exchange_code.upper(), product_type,
                            expiry_date, right, strike_price)
    except Exception as exc:
        resp = None
        primary_warn = str(exc)
    else:
        primary_warn = _breeze_error_msg(resp)

    data = (resp or {}).get("Success") or [] if resp and resp.get("Status") == 200 else []
    if data:
        return {"quote": data[0], "warning": None, "source": "cash"}

    # ── Index spot retry: Breeze indices work without product_type (empty string)
    # Try both "" and "cash" — the SDK default differs from explicit "cash" for indices.
    if stock_code.upper() in _INDEX_SYMBOLS:
        for pt in ("", "cash"):
            try:
                await asyncio.sleep(0.3)
                resp_retry = await _query("NSE", pt)
                data_retry = (resp_retry or {}).get("Success") or [] \
                             if resp_retry and resp_retry.get("Status") == 200 else []
                if data_retry:
                    return {"quote": data_retry[0], "warning": None, "source": f"nse_{pt or 'default'}"}
            except Exception:
                pass

    return {"quote": None, "warning": primary_warn}


# ── Research calls ───────────────────────────────────────────────────────────

class ResearchCallReq(BaseModel):
    stock_code:     str
    exchange_code:  str           = "NSE"
    bias:           str           = "BULLISH"   # BULLISH | BEARISH | NEUTRAL | WAIT
    trade_type:     str           = "LONG"      # LONG | SHORT | CALL | PUT | WATCH
    product:        str           = "cash"      # cash | options
    right:          Optional[str] = None        # CE | PE
    strike:         Optional[int] = None
    expiry:         Optional[str] = None
    cmp:            float         = 0.0         # market price at time of entry
    entry_price:    float         = 0.0         # numeric entry level
    entry_trigger:  str           = ""          # text description of entry condition
    target:         float         = 0.0
    target_text:    str           = ""          # e.g. "₹280-295" or "₹30-50 premium"
    stop_loss:      float         = 0.0
    quantity:       int           = 100
    horizon:        str           = "intraday"  # intraday | short_term | long_term
    why:            str           = ""          # rationale (full text)
    source:         str           = "ICICI Research"


@app.get("/api/research")
async def get_research():
    return {"calls": _research_calls}


@app.post("/api/research")
async def add_research(req: ResearchCallReq):
    global _research_seq
    _research_seq += 1
    # Auto-fill CMP from LTP cache if not provided
    cmp = req.cmp or _ltp_cache.get(req.stock_code.upper(), 0.0)
    call = {
        "id":            f"rc_{_research_seq}",
        "stock_code":    req.stock_code.upper(),
        "exchange_code": req.exchange_code,
        "bias":          req.bias.upper(),
        "trade_type":    req.trade_type.upper(),
        "product":       req.product,
        "right":         req.right,
        "strike":        req.strike,
        "expiry":        req.expiry,
        "cmp":           round(cmp, 2),
        "entry_price":   req.entry_price,
        "entry_trigger": req.entry_trigger,
        "target":        req.target,
        "target_text":   req.target_text,
        "stop_loss":     req.stop_loss,
        "quantity":      req.quantity,
        "horizon":       req.horizon,
        "why":           req.why,
        "source":        req.source,
        "status":        "pending",    # pending | acted | dismissed
        "added_at":      datetime.now().strftime("%H:%M:%S"),
    }
    _research_calls.append(call)
    await broadcast({"type": "research", "data": call})
    return call


@app.delete("/api/research/{call_id}")
async def dismiss_research(call_id: str):
    call = next((c for c in _research_calls if c["id"] == call_id), None)
    if not call:
        raise HTTPException(404, "Research call not found")
    call["status"] = "dismissed"
    return {"status": "dismissed", "id": call_id}


@app.post("/api/research/{call_id}/act")
async def act_on_research(call_id: str):
    """Convert an approved research call into a live trigger order."""
    _require_session()
    _require_live_trading()
    call = next((c for c in _research_calls if c["id"] == call_id and c["status"] == "pending"), None)
    if not call:
        raise HTTPException(404, "Pending research call not found")

    # Direction: bullish trades fire above trigger, bearish below
    is_bullish = call["bias"] in ("BULLISH",) or call["trade_type"] in ("LONG", "CALL")
    direction  = "above" if is_bullish else "below"
    trigger    = call["entry_price"] or _ltp_cache.get(call["stock_code"], 0)

    order_req = ManualOrderReq(
        stock_code    = call["stock_code"],
        exchange_code = call["exchange_code"],
        product       = call["product"],
        right         = call["right"],
        strike        = call["strike"],
        expiry        = call["expiry"],
        action        = "buy" if is_bullish else "sell",
        quantity      = call["quantity"],
        order_type    = "market",
    )
    trigger_req = TriggerOrderReq(
        watch_stock        = call["stock_code"],
        watch_exchange     = call["exchange_code"] if call["product"] == "cash" else "NSE",
        trigger_price      = float(trigger),
        trigger_direction  = direction,
        order              = order_req,
        time_limit_minutes = 240,
    )
    key  = f"{call['stock_code']}_{direction}_{trigger}"
    task = asyncio.create_task(_trigger_watcher(key, trigger_req))
    _trigger_tasks[key] = task
    call["status"] = "acted"
    await broadcast({
        "type":    "alert",
        "message": f"RESEARCH -> TRIGGER: {call['stock_code']} {call['recommendation']} @ ₹{trigger:,.2f}",
    })
    return {"status": "acted", "trigger_key": key}


# ── Suggestions ──────────────────────────────────────────────────────────────

def _brief_to_dict(brief) -> dict:
    """Serialise MorningBrief to a JSON-safe dict."""
    return {
        "bias":         brief.bias,
        "summary":      brief.summary,
        "generated_at": brief.generated_at,
        "source":       brief.source,
        "trades": [
            {
                "id":                t.id,
                "name":              t.name,
                "conviction":        t.conviction,
                "watch_stock":       t.watch_stock,
                "exchange":          t.exchange,
                "product":           t.product,
                "right":             t.right,
                "strike":            t.strike,
                "expiry":            t.expiry,
                "action":            t.action,
                "quantity":          t.quantity,
                "order_type":        t.order_type,
                "trigger_price":     t.trigger_price,
                "trigger_direction": t.trigger_direction,
                "target":            t.target,
                "stop_loss":         t.stop_loss,
                "max_spend":         t.max_spend,
                "rationale":         t.rationale,
                "status":            t.status,
            }
            for t in brief.trades
        ],
    }


@app.get("/api/suggestions")
async def get_suggestions(refresh: bool = False):
    """Return (or generate) the morning brief. Pass ?refresh=true to re-generate."""
    if _suggestion_engine is None:
        raise HTTPException(400, "Not connected — call POST /api/connect first.")
    brief = _suggestion_engine.get_brief()
    if brief is None or refresh:
        brief = await asyncio.to_thread(_suggestion_engine.generate)
    return _brief_to_dict(brief)


@app.post("/api/suggestions/{trade_id}/approve")
async def approve_suggestion(trade_id: str):
    """Approve a suggestion: marks it approved and auto-registers it as a trigger order."""
    if _suggestion_engine is None:
        raise HTTPException(400, "Not connected.")
    trade = _suggestion_engine.approve(trade_id)
    if trade is None:
        raise HTTPException(404, f"Trade id '{trade_id}' not found in current brief.")

    # Auto-register as a trigger order (requires live trading enabled + active session)
    trigger_key = None
    if _session and _session._api and _LIVE_TRADING_ENABLED:
        order_req = ManualOrderReq(
            stock_code    = trade.watch_stock,
            exchange_code = trade.exchange,
            product       = trade.product,
            right         = trade.right,
            strike        = trade.strike,
            expiry        = trade.expiry,
            action        = trade.action,
            quantity      = trade.quantity,
            order_type    = trade.order_type,
        )
        trigger_req = TriggerOrderReq(
            watch_stock        = trade.watch_stock,
            watch_exchange     = "NSE",
            trigger_price      = trade.trigger_price,
            trigger_direction  = trade.trigger_direction,
            order              = order_req,
            time_limit_minutes = 240,   # valid until market close (approx)
        )
        key  = f"{trade.watch_stock}_{trade.trigger_direction}_{trade.trigger_price}"
        task = asyncio.create_task(_trigger_watcher(key, trigger_req))
        _trigger_tasks[key] = task
        trigger_key = key
        await broadcast({
            "type":    "alert",
            "message": f"APPROVED: {trade.name} — trigger set @ ₹{trade.trigger_price:,.2f}",
        })
    else:
        await broadcast({
            "type":    "alert",
            "message": (
                f"APPROVED (saved): {trade.name} — connect Breeze to activate trigger."
            ),
        })

    return {"status": "approved", "trade_id": trade_id, "trigger_key": trigger_key}


@app.post("/api/suggestions/{trade_id}/skip")
async def skip_suggestion(trade_id: str):
    """Mark a suggestion as skipped."""
    if _suggestion_engine is None:
        raise HTTPException(400, "Not connected.")
    ok = _suggestion_engine.skip(trade_id)
    if not ok:
        raise HTTPException(404, f"Trade id '{trade_id}' not found.")
    return {"status": "skipped", "trade_id": trade_id}


# ── Chart workspace ───────────────────────────────────────────────────────────

@app.get("/charts")
async def charts_page():
    return FileResponse("static/charts.html")


@app.get("/api/ohlc")
async def get_ohlc(
    stock:    str,
    exchange: str = "NSE",
    product:  str = "cash",
    interval: str = "5minute",
    days:     int = 1,
    expiry:   str = "",
    right:    str = "",
    strike:   str = "0",
):
    """Fetch OHLC history from Breeze get_historical_data_v2."""
    _require_session()
    from datetime import timedelta, timezone
    valid = {"1second","1minute","5minute","30minute","1day"}
    if interval not in valid:
        raise HTTPException(400, f"interval must be one of {valid}")
    today   = datetime.now()
    from_dt = (today - timedelta(days=max(days, 1))).strftime("%Y-%m-%dT09:00:00.000Z")
    to_dt   = today.strftime("%Y-%m-%dT15:30:00.000Z")
    try:
        await asyncio.to_thread(_limiter.acquire, "get_historical_data_v2")
        resp = await asyncio.to_thread(
            _session.api.get_historical_data_v2,
            interval=interval,
            from_date=from_dt,
            to_date=to_dt,
            stock_code=stock,
            exchange_code=exchange,
            product_type=product,
            expiry_date=expiry,
            right=right,
            strike_price=strike,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if resp and resp.get("Status") == 200:
        return {"candles": resp.get("Success") or [], "count": len(resp.get("Success") or [])}
    return {"candles": [], "warning": _breeze_error_msg(resp)}


# ── Paper trading ────────────────────────────────────────────────────────────

@app.get("/paper")
async def paper_page():
    return FileResponse("static/paper.html")


class PaperOrderReq(BaseModel):
    stock_code:    str
    exchange_code: str           = "NSE"
    product:       str           = "cash"
    right:         Optional[str] = None
    strike:        Optional[int] = None
    expiry:        Optional[str] = None
    action:        str           = "buy"
    quantity:      int           = 75
    order_type:    str           = "market"
    price:         float         = 0.0


@app.post("/api/paper/order")
async def paper_place_order(req: PaperOrderReq):
    try:
        order = _paper.place_order(
            stock=req.stock_code.upper(),
            exchange=req.exchange_code,
            product=req.product,
            action=req.action,
            qty=req.quantity,
            order_type=req.order_type,
            price=req.price,
            ltp_cache=_ltp_cache,
            right=req.right,
            strike=req.strike,
            expiry=req.expiry,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    summary = _paper.summary(_ltp_cache)
    await broadcast({"type": "paper_update", "data": summary})
    return {"order": _paper._order_dict(order), "summary": summary}


@app.post("/api/paper/exit/{pos_id}")
async def paper_exit_position(pos_id: str):
    # Build effective LTP with DB fallback so exits work without live Breeze
    eff_ltp: Dict[str, float] = dict(_ltp_cache)
    pos = next((p for p in _paper._positions if p.id == pos_id and p.is_open), None)
    if pos and pos.symbol not in eff_ltp:
        fb = await asyncio.to_thread(_db_ltp_fallback, pos.symbol)
        if fb:
            eff_ltp[pos.symbol] = fb
    try:
        order = _paper.exit_position(pos_id, eff_ltp)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    summary = _paper.summary(eff_ltp)
    await broadcast({"type": "paper_update", "data": summary})
    return {"order": _paper._order_dict(order), "summary": summary}


@app.get("/api/paper/summary")
async def paper_summary():
    return _paper.summary(_ltp_cache)


class PaperSetLevelsReq(BaseModel):
    pos_id:    str
    sl_price:  float
    t1_price:  float
    t2_price:  float
    t1_qty:    int
    t2_qty:    int
    trail_pct: float = 0.004
    tag:       str   = ""


@app.post("/api/paper/set-levels")
async def paper_set_levels(req: PaperSetLevelsReq):
    ok = _paper.set_levels(
        pos_id=req.pos_id, sl_price=req.sl_price,
        t1_price=req.t1_price, t2_price=req.t2_price,
        t1_qty=req.t1_qty, t2_qty=req.t2_qty,
        trail_pct=req.trail_pct, tag=req.tag,
    )
    if not ok:
        raise HTTPException(404, f"Open position '{req.pos_id}' not found.")
    summary = _paper.summary(_ltp_cache)
    await broadcast({"type": "paper_update", "data": summary})
    return {"status": "ok", "pos_id": req.pos_id}


@app.post("/api/paper/partial-exit/{pos_id}")
async def paper_partial_exit(pos_id: str, body: dict):
    qty = int(body.get("qty", 0))
    if qty <= 0:
        raise HTTPException(400, "qty must be > 0")
    eff_ltp: Dict[str, float] = dict(_ltp_cache)
    pos = next((p for p in _paper._positions if p.id == pos_id and p.is_open), None)
    if pos and pos.symbol not in eff_ltp:
        fb = await asyncio.to_thread(_db_ltp_fallback, pos.symbol)
        if fb:
            eff_ltp[pos.symbol] = fb
    try:
        order = _paper.partial_exit(pos_id, qty, eff_ltp, tag="manual-partial")
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    summary = _paper.summary(eff_ltp)
    await broadcast({"type": "paper_update", "data": summary})
    return {"order": _paper._order_dict(order), "summary": summary}


@app.post("/api/paper/reset")
async def paper_reset(body: dict = {}):
    capital = float(body.get("starting_capital", _paper.starting_capital))
    _paper.starting_capital = capital
    _paper.reset()
    summary = _paper.summary(_ltp_cache)
    await broadcast({"type": "paper_update", "data": summary})
    return {"status": "reset", "starting_capital": capital}


@app.post("/api/paper/capital")
async def paper_set_capital(body: dict):
    capital = float(body.get("starting_capital", 1_000_000))
    if capital < 10_000:
        raise HTTPException(400, "Minimum starting capital is ₹10,000")
    _paper.starting_capital = capital
    _paper.cash = capital
    _paper.reset()
    return {"status": "ok", "starting_capital": capital}


# ── Symbol search ─────────────────────────────────────────────────────────────

@app.get("/api/symbols")
async def search_symbols(q: str = "", exchange: str = "", limit: int = 30):
    """Search symbols by stock code or company name.
    Supports multi-word queries — all words must appear in the name or code."""
    words = [w for w in q.strip().upper().split() if len(w) >= 2]
    ex    = exchange.strip().upper()

    if not words and not ex:
        return {"symbols": [], "total": 0, "hint": "Provide ?q= or ?exchange="}

    def _match(s: dict) -> bool:
        if ex and s["exchange"] != ex:
            return False
        if not words:
            return True
        code = s["stock_code"].upper()
        name = s["company_name"].upper()
        # Any word is a code prefix -> match
        if any(code.startswith(w) for w in words):
            return True
        # All words appear somewhere in the name -> match
        if all(w in name or w in code for w in words):
            return True
        # Single long word is a substring of the name -> match
        if len(words) == 1 and len(words[0]) >= 4 and words[0] in name:
            return True
        return False

    def _score(s: dict) -> tuple:
        code  = s["stock_code"].upper()
        name  = s["company_name"].upper()
        first = words[0] if words else ""
        # Equity before derivatives in mixed results
        exch_rank = 0 if s["exchange"] in ("NSE", "BSE") else 1
        if code == first:                        return (exch_rank, 0, code)
        if code.startswith(first):               return (exch_rank, 1, code)
        if words and all(w in name for w in words): return (exch_rank, 2, name)
        return (exch_rank, 3, name)

    matches = [s for s in _symbol_index if _match(s)]
    matches.sort(key=_score)
    return {"symbols": matches[:limit], "total": len(matches)}


@app.post("/api/symbols/refresh")
async def refresh_symbol_index():
    """Re-download the security master from Breeze and rebuild the index."""
    _require_session()
    await asyncio.to_thread(_session.api.get_stock_script_list)
    await asyncio.to_thread(_build_symbol_index)
    return {"status": "refreshed", "total": len(_symbol_index)}


# ── Tick pane & on-demand subscriptions ──────────────────────────────────────

class SubscribeReq(BaseModel):
    stock_code:    str
    exchange_code: str           = "NSE"
    product_type:  str           = "cash"
    right:         str           = ""
    strike:        str           = ""
    expiry_date:   str           = ""


@app.post("/api/ticks/watch")
async def set_tick_watch(body: dict):
    """Set which symbol the tick pane is watching. Returns recent tick history."""
    global _tick_watch
    symbol = (body.get("symbol") or "").upper().strip()
    _tick_watch = symbol or None
    history = list(_tick_log.get(symbol, []))[:100]
    return {"symbol": symbol, "watching": bool(symbol), "history": history}


@app.get("/api/ticks/{symbol}")
async def get_tick_history(symbol: str):
    """Return the last 200 ticks stored for a subscribed symbol."""
    key  = symbol.upper()
    data = list(_tick_log.get(key, []))
    return {"symbol": key, "count": len(data), "ticks": data}


@app.post("/api/subscribe")
async def subscribe_on_demand(req: SubscribeReq):
    """Subscribe to a Breeze WebSocket feed for any symbol on demand."""
    _require_session()
    cache_key = req.stock_code.upper()
    ok = await asyncio.to_thread(
        _ws_subscribe,
        req.stock_code.upper(),
        req.exchange_code,
        req.product_type,
        req.right.lower() if req.right else "",
        req.strike,
        req.expiry_date,
        cache_key,
    )
    if not ok:
        raise HTTPException(
            400,
            f"Could not subscribe to {req.stock_code} on {req.exchange_code}. "
            "Symbol may not exist in the Breeze security master, or the exchange/product type "
            "combination is incorrect."
        )
    return {"subscribed": cache_key, "all": list(_ws_subscriptions)}


@app.get("/api/quota")
async def get_quota():
    """Return Breeze REST call usage stats and current subscriptions."""
    return {
        **_limiter.stats,
        "subscribed_symbols": sorted(_ws_subscriptions),
        "tick_watch":         _tick_watch,
    }


# ── DB-backed OHLC (no Breeze session needed) ────────────────────────────────

_BREEZE_TO_DB = {
    "1minute": "1m", "5minute": "5m", "15minute": "15m",
    "30minute": "30m", "1day": "1d",
}


@app.get("/api/ohlc/db/available")
async def get_db_available():
    """Return which symbols + intervals are stored in PostgreSQL."""
    db_url = os.getenv("DB_URL", "")
    if not db_url:
        return {"data": [], "error": "DB_URL not configured"}
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol, "interval", COUNT(*) AS rows,
                   MIN(ts)::date AS from_date, MAX(ts)::date AS to_date
            FROM candles
            GROUP BY symbol, "interval"
            ORDER BY symbol, "interval"
        """)
        rows = cur.fetchall()
        conn.close()
        return {
            "data": [
                {"symbol": r[0], "interval": r[1], "rows": r[2],
                 "from": str(r[3]), "to": str(r[4])}
                for r in rows
            ]
        }
    except Exception as exc:
        return {"data": [], "error": str(exc)}


@app.get("/api/ohlc/db")
async def get_ohlc_db(
    symbol:   str,
    interval: str = "5minute",
    days:     int = 90,
):
    """Serve OHLC data from PostgreSQL — no Breeze session required."""
    db_url = os.getenv("DB_URL", "")
    if not db_url:
        raise HTTPException(400, "DB_URL not configured in .env")

    db_interval = _BREEZE_TO_DB.get(interval, interval)
    from_dt = datetime.now() - timedelta(days=max(days, 1))

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        cur.execute("""
            SELECT ts, open, high, low, close, volume
            FROM candles
            WHERE symbol = %s AND "interval" = %s AND ts >= %s
            ORDER BY ts
        """, (symbol.upper(), db_interval, from_dt))
        rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if not rows:
        return {
            "candles": [],
            "count":   0,
            "source":  "db",
            "warning": f"No data in DB for {symbol.upper()} [{db_interval}]. "
                       f"Connect Breeze to collect live data, or use the Download button for historical data.",
        }

    candles = [
        {
            "datetime": r[0].strftime("%Y-%m-%d %H:%M:%S"),
            "open":     str(r[1]),
            "high":     str(r[2]),
            "low":      str(r[3]),
            "close":    str(r[4]),
            "volume":   str(r[5]),
        }
        for r in rows
    ]
    return {"candles": candles, "count": len(candles), "source": "db"}


# ── Historical data download ──────────────────────────────────────────────────

@app.post("/api/data/download")
async def start_data_download(body: dict = {}):
    global _download_running, _download_log, _download_status

    if _download_running:
        raise HTTPException(409, "Download already in progress — wait for it to finish.")

    db_url = os.getenv("DB_URL", "")
    if not db_url:
        raise HTTPException(
            400,
            "DB_URL not set in .env — PostgreSQL is required to store downloaded data. "
            "See README for setup instructions.",
        )

    api_key       = (body.get("api_key")       or "").strip()
    api_secret    = (body.get("api_secret")     or "").strip()
    session_token = (body.get("session_token")  or "").strip()

    # Fall back to active session credentials if not provided
    if not api_key and _session:
        api_key       = _session.cfg.api_key
        api_secret    = _session.cfg.api_secret
        session_token = _session.cfg.session_token

    if not all([api_key, api_secret, session_token]):
        raise HTTPException(400, "Breeze credentials (api_key, api_secret, session_token) are required.")

    backfill_days       = int(body.get("backfill_days",       90))
    backfill_days_daily = int(body.get("backfill_days_daily", 730))

    # Optional symbol override: if provided, restrict to those symbols only (no futures)
    override_symbols: list = body.get("symbols") or []
    override_symbols = [s.strip().upper() for s in override_symbols if s]

    # Pre-calculate total work items so ETA is available from the first poll
    from collector.config import CollectorConfig as _Cfg
    _tmp = _Cfg(
        api_key=api_key, api_secret=api_secret,
        session_token=session_token, db_url=db_url,
        backfill_days=backfill_days, backfill_days_daily=backfill_days_daily,
    )
    if override_symbols:
        _tmp.symbols         = override_symbols
        _tmp.equity_symbols  = []
        _tmp.futures_symbols = []
    _spot_items    = len(_tmp.all_spot_symbols)  * len(_tmp.historical_intervals)
    _futures_items = len(_tmp.futures_symbols)   * _tmp.futures_num_expiries * len(_tmp.historical_intervals)
    _total_items   = _spot_items + _futures_items

    _download_running = True
    _download_log.clear()
    _download_status.update(
        status="running", current="Initialising…", error="",
        done_items=0, total_items=_total_items,
        start_ts=time.monotonic(), eta_sec=None,
    )

    def _run_download():
        global _download_running, _download_status

        # Attach a log handler so we capture backfill progress
        handler = _DownloadLogHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s — %(message)s"))
        backfill_logger = logging.getLogger("collector.historical")
        backfill_logger.addHandler(handler)

        try:
            from breeze_connect import BreezeConnect
            from collector.config import CollectorConfig
            from collector.historical import HistoricalBackfill
            from collector.store import DataStore

            _download_status["current"] = "Connecting to Breeze…"
            api = BreezeConnect(api_key=api_key)
            api.generate_session(api_secret=api_secret, session_token=session_token)

            _download_status["current"] = "Connecting to PostgreSQL…"
            store = DataStore(db_url)

            cfg = CollectorConfig(
                api_key=api_key,
                api_secret=api_secret,
                session_token=session_token,
                db_url=db_url,
                backfill_days=backfill_days,
                backfill_days_daily=backfill_days_daily,
            )
            if override_symbols:
                cfg.symbols         = override_symbols
                cfg.equity_symbols  = []
                cfg.futures_symbols = []

            _download_status["current"] = "Running backfill…"
            backfill = HistoricalBackfill(api, cfg, store)
            backfill.run()

            _download_status.update(status="complete", current="Done!", error="")
            log.info("Historical data download complete.")

        except Exception as exc:
            log.error("Historical download error: %s", exc, exc_info=True)
            _download_status.update(status="error", current="", error=str(exc))
        finally:
            backfill_logger.removeHandler(handler)
            _download_running = False

    threading.Thread(target=_run_download, daemon=True, name="data-download").start()
    return {"status": "started"}


@app.get("/api/data/status")
async def get_data_status():
    return {
        **_download_status,
        "running": _download_running,
        "log":     list(_download_log[-100:]),   # last 100 lines
    }



# Priority symbol queue for the range backfill — tried in order; any that return
# 0 candles from Breeze are marked "not available" and the next is tried.
_BACKFILL_PRIORITY: List[str] = [
    "NIFTY", "BANKNIFTY", "RELIND", "HDFBAN", "SBIN",
    "TCS", "INFY", "TATAMOTORS", "SUNPHARMA",
]


@app.post("/api/data/watchlist/backfill")
async def watchlist_full_backfill(req: Optional[WatchlistBackfillReq] = None):
    """
    Fetch OHLCV for a specific date window (defaults to last 1 year).

    Tries symbols from _BACKFILL_PRIORITY in order. Symbols that return 0 candles
    are marked "not available" — the run continues to the next symbol.
    Existing rows in DB are silently skipped (ON CONFLICT DO NOTHING).

    Intervals: 1m, 5m, 15m, 30m, 1d  (equity NSE cash — up to 10 years available).
    Runs in background; poll /api/data/status for progress.
    """
    global _download_running, _download_log, _download_status

    if _download_running:
        raise HTTPException(409, "A download is already in progress — wait for it to finish.")

    db_url = os.getenv("DB_URL", "")
    if not db_url:
        raise HTTPException(400, "DB_URL not configured in .env — PostgreSQL required.")

    if not (_session and _session._api):
        raise HTTPException(400, "Breeze session not connected — connect first then retry.")

    api_key       = _session.cfg.api_key
    api_secret    = _session.cfg.api_secret
    session_token = _session.cfg.session_token

    # Resolve date range
    today   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt   = datetime.strptime(req.to_date,   "%Y-%m-%d") if (req and req.to_date)   else today
    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d") if (req and req.from_date) else today - timedelta(days=365)

    symbols       = [s.upper().strip() for s in req.symbols] if (req and req.symbols) else list(_BACKFILL_PRIORITY)
    ivls          = ["1minute", "5minute", "30minute", "1day"]
    _total_items  = len(symbols) * len(ivls)

    _download_running = True
    _download_log.clear()
    _download_status.update(
        status="running",
        current=f"Starting range backfill {from_dt.date()} to {to_dt.date()} ...",
        error="", done_items=0, total_items=_total_items,
        start_ts=time.monotonic(), eta_sec=None,
    )

    def _run():
        global _download_running, _download_status

        handler = _DownloadLogHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s — %(message)s"))
        backfill_logger = logging.getLogger("collector.historical")
        backfill_logger.addHandler(handler)

        done_count = [0]

        def on_item_done(symbol: str, db_interval: str, sym_total: int):
            done_count[0] += 1
            elapsed = time.monotonic() - _download_status["start_ts"]
            pct     = done_count[0] / _total_items
            eta     = int(elapsed / pct * (1 - pct)) if pct > 0 else None
            _download_status.update(
                current   = f"[{symbol}] {db_interval} — {sym_total:,} candles so far",
                done_items= done_count[0],
                eta_sec   = eta,
            )

        try:
            from breeze_connect import BreezeConnect
            from collector.config import CollectorConfig
            from collector.historical import HistoricalBackfill
            from collector.store import DataStore

            api = BreezeConnect(api_key=api_key)
            api.generate_session(api_secret=api_secret, session_token=session_token)
            store = DataStore(db_url)

            cfg = CollectorConfig(
                api_key=api_key, api_secret=api_secret,
                session_token=session_token, db_url=db_url,
            )
            cfg.symbols         = symbols
            cfg.equity_symbols  = []
            cfg.futures_symbols = []
            cfg.historical_intervals = ivls

            results = HistoricalBackfill(api, cfg, store).run_range(
                from_dt=from_dt,
                to_dt=to_dt,
                symbols=symbols,
                on_item_done=on_item_done,
            )

            # Summarise results
            available = [s for s, r in results.items() if r["available"]]
            skipped   = [s for s, r in results.items() if not r["available"]]

            summary_lines = [
                f"Range backfill {from_dt.date()} to {to_dt.date()} complete.",
                f"Available ({len(available)}): {', '.join(available) or '—'}",
            ]
            if skipped:
                summary_lines.append(f"Not available ({len(skipped)}): {', '.join(skipped)}")
            for line in summary_lines:
                _download_log.append(line)
                log.info(line)

            _download_status.update(
                status  = "complete",
                current = summary_lines[0],
                error   = "",
            )

        except Exception as exc:
            log.error("Watchlist range backfill error: %s", exc, exc_info=True)
            _download_status.update(status="error", current="", error=str(exc))
        finally:
            backfill_logger.removeHandler(handler)
            _download_running = False

    threading.Thread(target=_run, daemon=True, name="watchlist-backfill").start()
    return {
        "status":    "started",
        "from_date": str(from_dt.date()),
        "to_date":   str(to_dt.date()),
        "symbols":   symbols,
        "intervals": ["1m", "5m", "15m", "30m", "1d"],
    }


@app.post("/api/data/nse_bulk")
async def start_nse_bulk_download(body: dict = {}):
    """
    Download Nifty 50 + Sensex 30 equity + F&O EOD from NSE public archives.
    No Breeze credentials required — uses NSE bhavcopy files directly.

    Body params (all optional):
      days        int   Calendar days of history to fetch  (default 730)
      equity_only bool  Skip F&O download
      fo_only     bool  Skip equity download
    """
    global _download_running, _download_log, _download_status

    if _download_running:
        raise HTTPException(409, "Download already in progress — wait for it to finish.")

    db_url = os.getenv("DB_URL", "")
    if not db_url:
        raise HTTPException(
            400,
            "DB_URL not set — PostgreSQL is required to store downloaded data.",
        )

    days        = int(body.get("days", 730))
    equity_only = bool(body.get("equity_only", False))
    fo_only     = bool(body.get("fo_only", False))

    _download_running = True
    _download_log.clear()
    _download_status.update(
        status="running", current="Connecting to NSE…", error="",
        done_items=0, total_items=days,   # one item per calendar day
        start_ts=time.monotonic(), eta_sec=None,
    )

    def _run_nse():
        global _download_running, _download_status
        try:
            from collector.nse_bulk_download import NSEBulkDownloader

            def _progress(msg: str) -> None:
                _download_log.append(msg)
                if len(_download_log) > 1000:
                    del _download_log[0]
                _download_status["current"] = msg[:120]
                # Lines like "[2024-05-15] equity= ..." mark a processed trading day
                if msg.startswith("[20") or msg.startswith("[19"):
                    _download_status["done_items"] += 1
                    done    = _download_status["done_items"]
                    total   = _download_status["total_items"]
                    elapsed = time.monotonic() - _download_status["start_ts"]
                    if done > 0 and elapsed > 0 and total > done:
                        _download_status["eta_sec"] = int((total - done) / (done / elapsed))

            NSEBulkDownloader(db_url=db_url, progress_cb=_progress).run(
                days=days,
                equity=not fo_only,
                fo=not equity_only,
            )
            _download_status.update(status="complete", current="Done!", error="")
            log.info("NSE bulk download complete.")
        except Exception as exc:
            log.error("NSE bulk download error: %s", exc, exc_info=True)
            _download_status.update(status="error", current="", error=str(exc))
        finally:
            _download_running = False

    threading.Thread(target=_run_nse, daemon=True, name="nse-bulk-download").start()
    return {"status": "started"}


# ── Intraday equity signal engine ────────────────────────────────────────────

def _ema_series(values: list, period: int) -> list:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _rsi14(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    return round(100 - (100 / (1 + ag / al)), 1) if al else 100.0


def _today_5m_candles(sym: str) -> list:
    """Return 5-min candles for strategy evaluation.

    Priority:
      1. Today's 5m candles from DB (most accurate for intraday strategies)
      2. Current live-forming 5m candle from in-memory accumulator
      3. If today has < 10 rows (market not open / no session), fall back to the
         most recent 80 historical 5m candles from DB so strategies can still
         produce signals based on recent price action.
    """
    today = datetime.now().date()
    rows: list = []
    if _db_store:
        try:
            raw = _db_store._queryall(
                "SELECT ts, open, high, low, close, volume FROM candles "
                "WHERE symbol=%s AND \"interval\"='5m' AND ts::date=%s ORDER BY ts",
                (sym, today),
            )
            rows = [{"ts": r[0], "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4]), "volume": int(r[5])}
                    for r in raw]
        except Exception:
            pass

    # Append current forming live candle (if for today and not already in rows)
    with _live_candles_lock:
        live = _live_candles.get(sym, {}).get(5)
        if live and hasattr(live.get("ts"), "date") and live["ts"].date() == today:
            if not any(c["ts"] == live["ts"] for c in rows):
                ltp = _ltp_cache.get(sym) or live["close"]
                rows.append({"ts": live["ts"], "open": live["open"], "high": live["high"],
                              "low": live["low"], "close": ltp, "volume": live["volume"]})

    # Fallback: use recent historical candles when today's data is insufficient
    # (market not open, Breeze not connected, or candle backfill not run today)
    if len(rows) < 10 and _db_store:
        try:
            raw = _db_store._queryall(
                "SELECT ts, open, high, low, close, volume FROM candles "
                "WHERE symbol=%s AND \"interval\"='5m' ORDER BY ts DESC LIMIT 80",
                (sym,),
            )
            if raw:
                rows = [{"ts": r[0], "open": float(r[1]), "high": float(r[2]),
                         "low": float(r[3]), "close": float(r[4]), "volume": int(r[5])}
                        for r in reversed(raw)]
                log.debug("5m historical fallback for %s: %d candles", sym, len(rows))
        except Exception:
            pass

    return rows


def _db_ltp_fallback(sym: str) -> Optional[float]:
    """Last available close from DB (any interval) when no live WebSocket price."""
    if not _db_store:
        return None
    try:
        row = _db_store._queryone(
            "SELECT close FROM candles WHERE symbol=%s AND close IS NOT NULL ORDER BY ts DESC LIMIT 1",
            (sym,),
        )
        return float(row[0]) if row and row[0] else None
    except Exception:
        return None


# ── Strategy evaluators ───────────────────────────────────────────────────────

def _sig_orb(sym: str, ltp: float, candles: list) -> dict:
    now_t = datetime.now().time()
    from datetime import time as _t
    if len(candles) < 3:
        return {"signal": "WAIT", "ltp": ltp,
                "reason": f"Only {len(candles)} 5-min candle(s) so far — opening range needs 3 (9:15–9:30)."}
    if now_t < _t(9, 30):
        return {"signal": "WAIT", "ltp": ltp,
                "reason": "Still inside the opening range window (9:15–9:30). Wait for 9:30 AM."}

    orb = candles[:3]
    orb_high = max(c["high"] for c in orb)
    orb_low  = min(c["low"]  for c in orb)
    vols     = [c["volume"] for c in candles if c["volume"] > 0]
    avg_vol  = _statistics.mean(vols) if vols else 1
    vol_ok   = (candles[-1]["volume"] >= avg_vol * 0.8)

    if ltp > orb_high:
        return {"signal": "LONG",  "ltp": ltp,
                "entry": ltp, "sl": round(orb_high * 0.995, 2),
                "target": round(ltp * 1.012, 2),
                "orb_high": round(orb_high, 2), "orb_low": round(orb_low, 2),
                "confidence": 0.75 if vol_ok else 0.55,
                "reason": f"Price ₹{ltp:.0f} broke above ORB high ₹{orb_high:.0f}."
                          f" Volume {'✓ confirmed' if vol_ok else '⚠ below avg'}."}
    if ltp < orb_low:
        return {"signal": "SHORT", "ltp": ltp,
                "entry": ltp, "sl": round(orb_low * 1.005, 2),
                "target": round(ltp * 0.988, 2),
                "orb_high": round(orb_high, 2), "orb_low": round(orb_low, 2),
                "confidence": 0.70 if vol_ok else 0.50,
                "reason": f"Price ₹{ltp:.0f} broke below ORB low ₹{orb_low:.0f}."
                          f" Volume {'✓ confirmed' if vol_ok else '⚠ below avg'}."}
    return {"signal": "WAIT", "ltp": ltp,
            "orb_high": round(orb_high, 2), "orb_low": round(orb_low, 2),
            "reason": f"Price ₹{ltp:.0f} inside ORB range [₹{orb_low:.0f}–₹{orb_high:.0f}]. Wait for breakout."}


def _sig_vwap(sym: str, ltp: float, candles: list) -> dict:
    if len(candles) < 2:
        return {"signal": "WAIT", "ltp": ltp, "reason": "Not enough candles for VWAP."}
    tv = sum((c["high"] + c["low"] + c["close"]) / 3 * c["volume"] for c in candles)
    tv_vol = sum(c["volume"] for c in candles)
    vwap = round(tv / tv_vol, 2) if tv_vol else ltp

    last, prev = candles[-1], candles[-2]
    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]
    bounce  = prev["close"] < vwap <= last["close"]
    reject  = prev["close"] > vwap >= last["close"]

    if ltp < vwap and bullish:
        return {"signal": "LONG",  "ltp": ltp, "vwap": vwap,
                "entry": ltp, "sl": round(last["low"] * 0.998, 2),
                "target": round(vwap * 1.005, 2),
                "confidence": 0.72 if bounce else 0.58,
                "reason": f"Price ₹{ltp:.0f} below VWAP ₹{vwap:.0f} with bullish reversal candle."
                          f"{' Fresh bounce from below VWAP.' if bounce else ''}"}
    if ltp > vwap and bearish:
        return {"signal": "SHORT", "ltp": ltp, "vwap": vwap,
                "entry": ltp, "sl": round(last["high"] * 1.002, 2),
                "target": round(vwap * 0.995, 2),
                "confidence": 0.68 if reject else 0.55,
                "reason": f"Price ₹{ltp:.0f} above VWAP ₹{vwap:.0f} with bearish rejection candle."
                          f"{' Fresh rejection from above VWAP.' if reject else ''}"}
    return {"signal": "WAIT", "ltp": ltp, "vwap": vwap,
            "reason": f"No clear VWAP reversal. VWAP=₹{vwap:.0f}, LTP=₹{ltp:.0f}."
                      f" Wait for a{'bullish' if ltp < vwap else ' bearish'} candle."}


def _sig_ema_cross(sym: str, ltp: float, candles: list) -> dict:
    if len(candles) < 22:
        return {"signal": "WAIT", "ltp": ltp,
                "reason": f"Need 22 five-min candles for EMA 9/21 — have {len(candles)}. Check back mid-morning."}
    closes  = [c["close"] for c in candles]
    e9      = _ema_series(closes, 9)
    e21     = _ema_series(closes, 21)
    offset  = len(e9) - len(e21)
    e9a     = e9[offset:]
    if len(e9a) < 2 or len(e21) < 2:
        return {"signal": "WAIT", "ltp": ltp, "reason": "Insufficient data for EMA alignment."}

    cur_bull  = e9a[-1] > e21[-1]
    prev_bull = e9a[-2] > e21[-2]

    if cur_bull and not prev_bull:
        return {"signal": "LONG",  "ltp": ltp,
                "entry": ltp, "sl": round(candles[-1]["low"] * 0.998, 2),
                "target": round(ltp * 1.015, 2),
                "ema9": round(e9a[-1], 2), "ema21": round(e21[-1], 2),
                "confidence": 0.72,
                "reason": f"EMA9 ({e9a[-1]:.0f}) just crossed ABOVE EMA21 ({e21[-1]:.0f}). Fresh bullish crossover."}
    if not cur_bull and prev_bull:
        return {"signal": "SHORT", "ltp": ltp,
                "entry": ltp, "sl": round(candles[-1]["high"] * 1.002, 2),
                "target": round(ltp * 0.985, 2),
                "ema9": round(e9a[-1], 2), "ema21": round(e21[-1], 2),
                "confidence": 0.68,
                "reason": f"EMA9 ({e9a[-1]:.0f}) just crossed BELOW EMA21 ({e21[-1]:.0f}). Fresh bearish crossover."}
    trend = "bullish" if cur_bull else "bearish"
    return {"signal": "WAIT", "ltp": ltp,
            "ema9": round(e9a[-1], 2), "ema21": round(e21[-1], 2),
            "reason": f"EMA9/21 trend is {trend} but no fresh crossover. Wait for next crossover."}


def _sig_sr_reversal(sym: str, ltp: float, candles: list) -> dict:
    if len(candles) < 15:
        return {"signal": "WAIT", "ltp": ltp,
                "reason": f"Need 15 candles for RSI(14) — have {len(candles)}."}
    closes   = [c["close"] for c in candles]
    rsi      = _rsi14(closes)
    day_high = max(c["high"] for c in candles)
    day_low  = min(c["low"]  for c in candles)
    pivot    = (day_high + day_low + closes[-1]) / 3
    r1       = round(2 * pivot - day_low, 2)
    s1       = round(2 * pivot - day_high, 2)

    if rsi < 30:
        return {"signal": "LONG",  "ltp": ltp, "rsi": rsi,
                "entry": ltp, "sl": round(day_low * 0.999, 2),
                "target": round(ltp * 1.015, 2),
                "support": s1, "resistance": r1,
                "confidence": 0.70,
                "reason": f"RSI {rsi} is oversold (<30) near support ₹{s1:.0f}. Mean-reversion bounce expected."}
    if rsi > 70:
        return {"signal": "SHORT", "ltp": ltp, "rsi": rsi,
                "entry": ltp, "sl": round(day_high * 1.001, 2),
                "target": round(ltp * 0.985, 2),
                "support": s1, "resistance": r1,
                "confidence": 0.65,
                "reason": f"RSI {rsi} is overbought (>70) near resistance ₹{r1:.0f}. Reversal expected."}
    return {"signal": "WAIT", "ltp": ltp, "rsi": rsi,
            "support": s1, "resistance": r1,
            "reason": f"RSI {rsi} is neutral (30–70). Wait for extreme reading near S/R levels."}


def _sig_gap_go(sym: str, ltp: float, candles: list) -> dict:
    prev_close = None
    if _db_store:
        today = datetime.now().date()
        for n in range(1, 6):
            d = today - timedelta(days=n)
            row = _db_store._queryone(
                "SELECT close FROM candles WHERE symbol=%s AND \"interval\"='1d' AND ts::date=%s",
                (sym, d),
            )
            if row and row[0]:
                prev_close = float(row[0])
                break
    if not prev_close:
        return {"signal": "WAIT", "ltp": ltp,
                "reason": "No previous day close in DB. Download 1D data first (NSE Bulk Download)."}

    today_open  = candles[0]["open"] if candles else ltp
    gap_pct     = round((today_open - prev_close) / prev_close * 100, 2)
    cont_up     = ltp > today_open
    cont_down   = ltp < today_open

    if gap_pct > 1.5 and cont_up:
        return {"signal": "LONG",  "ltp": ltp, "gap_pct": gap_pct,
                "entry": ltp, "sl": round(today_open * 0.994, 2),
                "target": round(ltp * 1.020, 2),
                "confidence": 0.72,
                "reason": f"Gap up +{gap_pct:.1f}% (prev ₹{prev_close:.0f} -> open ₹{today_open:.0f}). Price continuing higher — momentum buy."}
    if gap_pct < -1.5 and cont_down:
        return {"signal": "SHORT", "ltp": ltp, "gap_pct": gap_pct,
                "entry": ltp, "sl": round(today_open * 1.006, 2),
                "target": round(ltp * 0.980, 2),
                "confidence": 0.68,
                "reason": f"Gap down {gap_pct:.1f}% (prev ₹{prev_close:.0f} -> open ₹{today_open:.0f}). Selling continuing — momentum short."}
    if abs(gap_pct) > 1.5:
        return {"signal": "WAIT", "ltp": ltp, "gap_pct": gap_pct,
                "reason": f"Gap {'up' if gap_pct > 0 else 'down'} {abs(gap_pct):.1f}% but price not continuing in gap direction. May fill gap — wait."}
    return {"signal": "WAIT", "ltp": ltp, "gap_pct": gap_pct,
            "reason": f"Gap {gap_pct:+.1f}% is below ±1.5% threshold — no Gap & Go signal today."}


_INTRADAY_EVALUATORS = {
    "orb":         _sig_orb,
    "vwap":        _sig_vwap,
    "ema_cross":   _sig_ema_cross,
    "sr_reversal": _sig_sr_reversal,
    "gap_go":      _sig_gap_go,
}

_INTRADAY_NAMES = {
    "orb":         "ORB",
    "vwap":        "VWAP Reversal",
    "ema_cross":   "EMA Crossover",
    "sr_reversal": "S&R Reversal",
    "gap_go":      "Gap & Go",
}


# ── Options signal evaluators ─────────────────────────────────────────────────

def _nearest_expiry_from_db(sym: str) -> Optional[date]:
    """Return nearest future expiry from chain or PCR snapshots."""
    if not _db_store:
        return None
    today = datetime.now().date()
    for table in ("pcr_snapshots", "chain_snapshots"):
        try:
            row = _db_store._queryone(
                f"SELECT MIN(expiry) FROM {table} WHERE symbol=%s AND expiry >= %s",
                (sym, today),
            )
            if row and row[0]:
                return row[0]
        except Exception:
            continue
    return None


def _sig_iv_rank(sym: str, ltp: float) -> dict:
    """HIGH IV Rank (≥70%) -> sell premium (Iron Condor). LOW (≤30%) -> buy premium (Long Straddle)."""
    if not _db_store:
        return {"signal": "NO_DATA", "reason": "No DB connected."}
    try:
        row = _db_store._queryone(
            "SELECT atm_iv, iv_rank, iv_pctile FROM iv_daily WHERE symbol=%s ORDER BY date DESC LIMIT 1",
            (sym,),
        )
        if not row or row[0] is None:
            return {"signal": "WAIT",
                    "reason": "No IV history in DB. Run NSE Bulk Download first."}
        atm_iv    = float(row[0])
        iv_rank   = float(row[1]) if row[1] is not None else None
        iv_pctile = float(row[2]) if row[2] is not None else None

        if iv_rank is None:
            df = _db_store.get_iv_history(sym, lookback_days=252)
            if len(df) < 30:
                return {"signal": "WAIT",
                        "reason": f"Only {len(df)} days of IV history — need 30+ for IV Rank."}
            vals = df["atm_iv"].dropna().tolist()
            iv_min, iv_max = min(vals), max(vals)
            iv_rank = (atm_iv - iv_min) / (iv_max - iv_min) * 100 if iv_max > iv_min else 50.0

        if iv_rank >= 70:
            # Capital-preservation mode: always suggest Iron Condor (defined max loss)
            # Short Strangle is higher-yield but unlimited risk — not auto-suggested
            sugg, sugg_name = "iron_condor", "Iron Condor"
            reason = (f"IV Rank {iv_rank:.0f}% is HIGH (≥70%) — premium is expensive. "
                      f"Iron Condor recommended: defined max loss, wide strikes (3 steps).")
            conf = 0.80 if iv_rank >= 85 else 0.70
            return {
                "signal": "SHORT", "ltp": ltp,
                "iv": round(atm_iv, 2), "iv_rank": round(iv_rank, 1),
                "iv_pctile": round(iv_pctile, 1) if iv_pctile else None,
                "suggested_strategy": sugg,
                "suggested_strategy_name": sugg_name,
                "confidence": conf,
                "reason": reason,
            }
        if iv_rank <= 30:
            return {
                "signal": "LONG", "ltp": ltp,
                "iv": round(atm_iv, 2), "iv_rank": round(iv_rank, 1),
                "iv_pctile": round(iv_pctile, 1) if iv_pctile else None,
                "suggested_strategy": "long_straddle",
                "suggested_strategy_name": "Long Straddle",
                "confidence": 0.72 if iv_rank <= 20 else 0.60,
                "reason": (f"IV Rank {iv_rank:.0f}% is LOW (≤30%) — premium is cheap. "
                           f"Buy premium: Long Straddle."),
            }
        return {"signal": "WAIT", "ltp": ltp,
                "iv": round(atm_iv, 2), "iv_rank": round(iv_rank, 1),
                "reason": f"IV Rank {iv_rank:.0f}% is neutral (30–70%). No extreme IV condition."}
    except Exception as exc:
        return {"signal": "ERROR", "reason": str(exc)}


def _sig_pcr_sentiment(sym: str, ltp: float) -> dict:
    """PCR ≥1.3 -> contrarian LONG (Bull Call Spread). PCR ≤0.7 -> contrarian SHORT (Bear Put Spread)."""
    if not _db_store:
        return {"signal": "NO_DATA", "reason": "No DB connected."}
    try:
        row = _db_store._queryone(
            "SELECT pcr, call_oi, put_oi FROM pcr_snapshots WHERE symbol=%s ORDER BY ts DESC LIMIT 1",
            (sym,),
        )
        if not row or row[0] is None:
            return {"signal": "WAIT",
                    "reason": "No PCR data yet. Start chain collector or wait for snapshot."}
        pcr     = float(row[0])
        call_oi = int(row[1]) if row[1] else 0
        put_oi  = int(row[2]) if row[2] else 0

        if pcr >= 1.3:
            return {
                "signal": "LONG", "ltp": ltp, "pcr": round(pcr, 2),
                "call_oi": call_oi, "put_oi": put_oi,
                "suggested_strategy": "bull_call_spread",
                "suggested_strategy_name": "Bull Call Spread",
                "confidence": 0.72 if pcr >= 1.5 else 0.62,
                "reason": (f"PCR {pcr:.2f} ≥1.3 — excess put buying signals bearish panic. "
                           f"Contrarian LONG: Bull Call Spread."),
            }
        if pcr <= 0.7:
            return {
                "signal": "SHORT", "ltp": ltp, "pcr": round(pcr, 2),
                "call_oi": call_oi, "put_oi": put_oi,
                "suggested_strategy": "bear_put_spread",
                "suggested_strategy_name": "Bear Put Spread",
                "confidence": 0.68 if pcr <= 0.5 else 0.58,
                "reason": (f"PCR {pcr:.2f} ≤0.7 — excess call buying signals complacency. "
                           f"Contrarian SHORT: Bear Put Spread."),
            }
        return {"signal": "WAIT", "ltp": ltp, "pcr": round(pcr, 2),
                "reason": f"PCR {pcr:.2f} is neutral (0.7–1.3). No extreme reading."}
    except Exception as exc:
        return {"signal": "ERROR", "reason": str(exc)}


def _sig_max_pain(sym: str, ltp: float) -> dict:
    """LTP far from max pain with ≤10 DTE -> expect drift toward max pain."""
    if not _db_store:
        return {"signal": "NO_DATA", "reason": "No DB connected."}
    try:
        today  = datetime.now().date()
        expiry = _nearest_expiry_from_db(sym)
        if not expiry:
            return {"signal": "WAIT",
                    "reason": "No expiry found in DB. Start chain collector."}
        dte = (expiry - today).days
        if dte > 15:
            return {"signal": "WAIT", "ltp": ltp,
                    "reason": f"Expiry {expiry} is {dte} DTE — max pain pull is weak beyond 15 DTE."}

        rows = _db_store._queryall(
            """SELECT strike, "right", oi FROM chain_snapshots
               WHERE symbol=%s AND expiry=%s AND oi > 0
                 AND ts = (SELECT MAX(ts) FROM chain_snapshots WHERE symbol=%s AND expiry=%s)
               ORDER BY strike""",
            (sym, expiry, sym, expiry),
        )
        if not rows:
            return {"signal": "WAIT",
                    "reason": "No chain snapshot data for nearest expiry."}

        call_oi: dict = {}
        put_oi:  dict = {}
        for strike, right, oi in rows:
            k = float(strike)
            o = int(oi)
            if right == "CE":
                call_oi[k] = o
            elif right == "PE":
                put_oi[k]  = o

        all_strikes = sorted(set(call_oi) | set(put_oi))
        if not all_strikes:
            return {"signal": "WAIT", "reason": "Insufficient OI data to compute max pain."}

        min_pain, max_pain_strike = float("inf"), all_strikes[0]
        for p in all_strikes:
            total = (sum(max(0.0, p - k) * call_oi.get(k, 0) for k in all_strikes) +
                     sum(max(0.0, k - p) * put_oi.get(k, 0) for k in all_strikes))
            if total < min_pain:
                min_pain, max_pain_strike = total, p

        dist_pct = abs(ltp - max_pain_strike) / ltp * 100
        if dist_pct >= 0.5 and dte <= 10:
            direction = "LONG" if ltp < max_pain_strike else "SHORT"
            strat     = "bull_call_spread" if direction == "LONG" else "bear_put_spread"
            return {
                "signal": direction, "ltp": ltp,
                "max_pain": round(max_pain_strike, 2), "dte": dte,
                "distance_pct": round(dist_pct, 2),
                "suggested_strategy": strat,
                "suggested_strategy_name": "Bull Call Spread" if direction == "LONG" else "Bear Put Spread",
                "confidence": 0.68 if dte <= 5 else 0.58,
                "reason": (f"Max pain ₹{max_pain_strike:.0f} vs LTP ₹{ltp:.0f} "
                           f"({dist_pct:.1f}% away, {dte} DTE). Price tends to drift toward max pain."),
            }
        return {"signal": "WAIT", "ltp": ltp,
                "max_pain": round(max_pain_strike, 2), "dte": dte,
                "reason": (f"Max pain ₹{max_pain_strike:.0f}, LTP ₹{ltp:.0f} — "
                           f"{'gap too small (<0.5%)' if dist_pct < 0.5 else f'{dte} DTE too far'}"
                           f" for strong pull.")}
    except Exception as exc:
        return {"signal": "ERROR", "reason": str(exc)}


_OPTIONS_EVALUATORS = {
    "iv_rank":  _sig_iv_rank,
    "pcr":      _sig_pcr_sentiment,
    "max_pain": _sig_max_pain,
}

_OPTIONS_NAMES = {
    "iv_rank":  "IV Rank",
    "pcr":      "PCR Sentiment",
    "max_pain": "Max Pain",
}


# ── Shared scan helper (equity + options, used by endpoint + monitor loop) ────

async def _run_scan(sym_list: list) -> dict:
    """Evaluate all equity and options strategies for every symbol in sym_list."""
    now_str = _now_ist().strftime("%H:%M:%S")
    results: list = []

    for sym in sym_list:
        live_ltp = _ltp_cache.get(sym)
        candles  = await asyncio.to_thread(_today_5m_candles, sym)

        if live_ltp:
            ltp, ltp_source = live_ltp, "live"
        elif candles:
            ltp, ltp_source = candles[-1]["close"], "5m-candle"
        else:
            ltp = await asyncio.to_thread(_db_ltp_fallback, sym)
            ltp_source = "db-close" if ltp else None

        # ── Equity strategies ──────────────────────────────────────────────
        for strat_id, fn in _INTRADAY_EVALUATORS.items():
            try:
                sig = fn(sym, ltp, candles) if ltp else {
                    "signal": "NO_DATA",
                    "reason": "No price data. Subscribe on Live Dashboard or download historical data.",
                }
            except Exception as exc:
                sig = {"signal": "ERROR", "reason": str(exc)}
            row: dict = {
                "symbol": sym, "strategy": strat_id,
                "strategy_name": _INTRADAY_NAMES.get(strat_id, strat_id),
                "type": "equity",
                "ltp": ltp, "ltp_source": ltp_source, **sig,
            }
            if sig.get("signal") in ("LONG", "SHORT"):
                row["triggered_at"] = now_str
            results.append(row)

        # ── Options strategies ─────────────────────────────────────────────
        for strat_id, fn in _OPTIONS_EVALUATORS.items():
            try:
                sig = await asyncio.to_thread(fn, sym, ltp) if ltp else {
                    "signal": "NO_DATA",
                    "reason": "No price data.",
                }
            except Exception as exc:
                sig = {"signal": "ERROR", "reason": str(exc)}
            row = {
                "symbol": sym, "strategy": strat_id,
                "strategy_name": _OPTIONS_NAMES.get(strat_id, strat_id),
                "type": "options",
                "ltp": ltp, "ltp_source": ltp_source, **sig,
            }
            if sig.get("signal") in ("LONG", "SHORT"):
                row["triggered_at"] = now_str
            results.append(row)

    results.sort(key=lambda r: (
        0 if r.get("signal") in ("LONG", "SHORT") else 1,
        -(r.get("confidence") or 0),
    ))
    actionable = [r for r in results if r.get("signal") in ("LONG", "SHORT")]
    return {
        "results":    results,
        "scanned_at": now_str,
        "symbols":    sym_list,
        "total":      len(results),
        "actionable": len(actionable),
    }


@app.get("/api/intraday/scan")
async def scan_intraday_signals(symbols: str = "NIFTY,BANKNIFTY,RELIANCE,HDFCBANK,TCS",
                                cached: bool = False):
    """
    Evaluate all 5 intraday strategies for a comma-separated symbol list.

    During market hours the server-side monitor already runs every 60 s and
    caches results. If the cached payload covers the requested symbols and is
    ≤90 s old, it is returned immediately (no extra DB/compute cost).
    Pass cached=false to force a fresh live evaluation.
    """
    sym_list = [_normalize_symbol(s.strip().upper()) for s in symbols.split(",") if s.strip()][:12]

    # Return server-side cache when symbols match and it is fresh enough
    if _intraday_scan_cache and cached is not False:
        cache_syms = set(_intraday_scan_cache.get("symbols", []))
        if set(sym_list) <= cache_syms:
            return _intraday_scan_cache

    return await _run_scan(sym_list)


@app.get("/api/intraday/signal")
async def get_intraday_signal(symbol: str = "NIFTY", strategy: str = "orb"):
    """Evaluate one of 5 intraday strategy signals for a given symbol."""
    sym = _normalize_symbol(symbol.strip().upper())
    ltp = _ltp_cache.get(sym)

    candles = await asyncio.to_thread(_today_5m_candles, sym)

    if not ltp and candles:
        ltp = candles[-1]["close"]
    if not ltp:
        ltp = await asyncio.to_thread(_db_ltp_fallback, sym)
    if not ltp:
        return {"signal": "NO_DATA", "ltp": None,
                "reason": "No price data for this symbol. Subscribe on Live Dashboard or download historical data."}

    fn = _INTRADAY_EVALUATORS.get(strategy)
    if not fn:
        return {"signal": "ERROR", "reason": f"Unknown strategy '{strategy}'."}

    return fn(sym, ltp, candles)


# ── Paper strategy trades ─────────────────────────────────────────────────────

class PaperStrategyReq(BaseModel):
    strategy_id:   str
    stock:         str
    exchange:      str = "NFO"
    expiry:        str              # YYYY-MM-DD
    lots:          int = 1
    short_steps:   int = 2         # IC / covered call OTM distance
    width_steps:   int = 2         # IC / spread width
    leg_prices:    List[float] = []  # manual prices per leg (empty = use LTP)


@app.post("/api/paper/strategy/enter")
async def paper_strategy_enter(req: PaperStrategyReq):
    from trade_engine.option_strategies import (
        STRATEGY_BUILDERS, STRATEGY_NAMES, STRIKE_STEPS, LOT_SIZES,
    )
    stock = _normalize_symbol(req.stock)   # resolve "HDFC BANK" -> "HDFCBANK" etc.

    builder = STRATEGY_BUILDERS.get(req.strategy_id)
    if not builder:
        raise HTTPException(400, f"Unknown strategy: {req.strategy_id}")

    spot = _ltp_cache.get(stock)
    if not spot:
        raise HTTPException(400,
            f"No live LTP for {stock}. Connect to Breeze and subscribe this symbol first.")

    step     = STRIKE_STEPS.get(stock, 50)
    lot_size = LOT_SIZES.get(stock, 75)

    kwargs: dict = dict(spot=spot, step=step, lots=req.lots, lot_size=lot_size)
    if req.strategy_id in ("iron_condor",):
        kwargs.update(short_steps=req.short_steps, width_steps=req.width_steps)
    elif req.strategy_id in ("bull_call_spread", "bear_put_spread"):
        kwargs.update(width_steps=req.width_steps)
    elif req.strategy_id in ("covered_call", "short_strangle"):
        kwargs.update(otm_steps=req.short_steps)

    plan    = builder(**kwargs)
    legs    = [l.to_dict() for l in plan["legs"]]

    # Overlay manual prices if provided
    for i, price in enumerate(req.leg_prices):
        if i < len(legs) and price > 0:
            legs[i]["price"] = price

    try:
        trade = _paper.enter_strategy(
            strategy_id        = req.strategy_id,
            strategy_name      = STRATEGY_NAMES[req.strategy_id],
            stock              = stock,
            exchange           = req.exchange,
            expiry             = req.expiry,
            legs               = legs,
            ltp_cache          = _ltp_cache,
            break_even_lower   = plan.get("break_even_lower"),
            break_even_upper   = plan.get("break_even_upper"),
        )
        await broadcast({"type": "paper_strategy_entered", "trade": trade})
        return {"ok": True, "trade": trade,
                "break_even_lower": trade.get("break_even_lower"),
                "break_even_upper": trade.get("break_even_upper")}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/paper/strategy/exit/{trade_id}")
async def paper_strategy_exit(trade_id: str):
    try:
        trade, pnl = _paper.exit_strategy(trade_id, _ltp_cache)
        await broadcast({"type": "paper_strategy_closed",
                         "trade_id": trade_id, "pnl": pnl})
        return {"ok": True, "trade": trade, "realised_pnl": pnl}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/paper/strategies")
async def paper_strategy_list():
    return {"trades": _paper.strategy_summary(_ltp_cache)}


@app.get("/api/paper/strategy/plan")
async def paper_strategy_plan(
    strategy_id: str,
    stock:       str,
    lots:        int = 1,
    short_steps: int = 2,
    width_steps: int = 2,
):
    """Preview the legs and strikes without entering the trade."""
    from trade_engine.option_strategies import (
        STRATEGY_BUILDERS, STRATEGY_NAMES, STRIKE_STEPS, LOT_SIZES,
    )
    stock = _normalize_symbol(stock)   # resolve display names to Breeze codes

    builder = STRATEGY_BUILDERS.get(strategy_id)
    if not builder:
        raise HTTPException(400, f"Unknown strategy: {strategy_id}")

    spot = _ltp_cache.get(stock)
    if not spot:
        raise HTTPException(400,
            f"No live LTP for {stock}. Connect to Breeze and subscribe this symbol first.")

    step     = STRIKE_STEPS.get(stock, 50)
    lot_size = LOT_SIZES.get(stock, 75)

    kwargs: dict = dict(spot=spot, step=step, lots=lots, lot_size=lot_size)
    if strategy_id == "iron_condor":
        kwargs.update(short_steps=short_steps, width_steps=width_steps)
    elif strategy_id in ("bull_call_spread", "bear_put_spread"):
        kwargs.update(width_steps=width_steps)
    elif strategy_id in ("covered_call", "short_strangle"):
        kwargs.update(otm_steps=short_steps)

    plan = builder(**kwargs)
    legs_preview = []
    for leg in plan["legs"]:
        sym = f"{stock}_{leg.right}_{leg.strike}" if leg.right and leg.strike else stock
        ltp = _ltp_cache.get(sym) or 0
        legs_preview.append({**leg.to_dict(), "live_price": ltp})

    return {
        "strategy":    STRATEGY_NAMES[strategy_id],
        "description": plan["description"],
        "atm":         plan["atm"],
        "spot":        spot,
        "legs":        legs_preview,
        "break_even_lower": plan.get("break_even_lower"),
        "break_even_upper": plan.get("break_even_upper"),
    }


# ── Strategy runner API ───────────────────────────────────────────────────────

class StrategyStartReq(BaseModel):
    strategy_id: str
    params:      dict  = {}
    mode:        str   = "paper"   # paper | live
    auto_exec:   bool  = False


@app.post("/api/strategy/start")
async def strategy_start(req: StrategyStartReq):
    from trade_engine.strategy_signals import STRATEGY_REGISTRY
    cls = STRATEGY_REGISTRY.get(req.strategy_id)
    if not cls:
        return {"ok": False, "error": f"Unknown strategy: {req.strategy_id}"}
    if req.strategy_id in _active_strategies:
        return {"ok": False, "error": "Already running"}
    if req.mode == "live" and not (_session and _session._api):
        return {"ok": False, "error": "Live mode requires an active Breeze session"}

    instance = cls(req.params)
    _active_strategies[req.strategy_id] = {
        "instance":  instance,
        "cfg":       req.params,
        "mode":      req.mode,
        "auto_exec": req.auto_exec,
        "symbols":   req.params.get("symbols", []),
        "started_at": datetime.now().isoformat(),
        "signal_count": 0,
    }
    log.info("Strategy started: %s  mode=%s  symbols=%s",
             req.strategy_id, req.mode, req.params.get("symbols"))
    return {"ok": True, "strategy_id": req.strategy_id,
            "mode": req.mode, "symbols": req.params.get("symbols", [])}


@app.post("/api/strategy/stop")
async def strategy_stop(body: dict):
    sid = body.get("strategy_id", "")
    if sid not in _active_strategies:
        return {"ok": False, "error": "Not running"}
    del _active_strategies[sid]
    log.info("Strategy stopped: %s", sid)
    return {"ok": True}


@app.get("/api/strategy/list")
async def strategy_list():
    runs = [
        {
            "strategy_id":  sid,
            "mode":         run["mode"],
            "symbols":      run["symbols"],
            "started_at":   run["started_at"],
            "signal_count": run["signal_count"],
            "auto_exec":    run["auto_exec"],
        }
        for sid, run in _active_strategies.items()
    ]
    return {"runs": runs}


@app.get("/api/strategy/signals")
async def strategy_signals(limit: int = 100):
    return {"signals": list(_strategy_signals)[:limit]}


# ── Watchlist LTP snapshot (persist & restore across restarts) ───────────────

# Legacy Breeze code aliases: old NFO/scrip code -> canonical NSE cash code used now.
# Used so page-seed still works when DB has rows under the old code.
_WL_ALIASES: Dict[str, str] = {
    "HDFCBANK": "HDFBAN",   # old WS/candle data stored as HDFBAN
    "CNXBAN":   "BANKNIFTY", # old data stored as BANKNIFTY; Breeze NSE cash code is CNXBAN
}

@app.get("/api/watchlist/ltp")
async def watchlist_ltp(symbols: str = "NIFTY,CNXBAN,RELIND,TCS,HDFCBANK"):
    """
    Return last-known LTP + prev_close for watchlist symbols.
    Priority: 1) live cache  2) watchlist_state (has prev_close)  3) spot_ticks  4) candles
    """
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    result: dict = {}

    # 1. Live WebSocket cache
    for sym in syms:
        if sym in _ltp_cache:
            result[sym] = {"ltp": _ltp_cache[sym], "source": "live"}

    # 2. watchlist_state — best source: has both ltp and prev_close from last Update
    missing = [s for s in syms if s not in result]
    if missing and _db_store:
        try:
            alias_lookup: Dict[str, str] = {}
            lookup_codes = []
            for sym in missing:
                lookup_codes.append(sym)
                alias = _WL_ALIASES.get(sym)
                if alias:
                    lookup_codes.append(alias)
                    alias_lookup[alias] = sym
            rows = await asyncio.to_thread(_db_store.get_watchlist_state, lookup_codes)
            for row in rows:
                canonical = alias_lookup.get(row["symbol"], row["symbol"])
                if canonical not in result and row["ltp"]:
                    result[canonical] = {
                        "ltp":        row["ltp"],
                        "prev_close": row["prev_close"],
                        "ts":         row["ts"].isoformat() if row["ts"] else None,
                        "source":     "state",
                    }
        except Exception as exc:
            log.warning("watchlist_ltp state lookup failed: %s", exc)

    # 3. spot_ticks fallback (ltp only, no prev_close)
    missing = [s for s in syms if s not in result]
    if missing and _db_store:
        try:
            alias_lookup2: Dict[str, str] = {}
            lookup_codes2 = []
            for sym in missing:
                lookup_codes2.append(sym)
                alias = _WL_ALIASES.get(sym)
                if alias:
                    lookup_codes2.append(alias)
                    alias_lookup2[alias] = sym
            rows = await asyncio.to_thread(_db_store.get_latest_ltp, lookup_codes2)
            for row in rows:
                canonical = alias_lookup2.get(row["symbol"], row["symbol"])
                if canonical not in result:
                    result[canonical] = {
                        "ltp":    row["ltp"],
                        "ts":     row["ts"].isoformat() if row["ts"] else None,
                        "source": "db",
                    }
        except Exception as exc:
            log.warning("watchlist_ltp DB fallback failed: %s", exc)

    # 4. Candles fallback
    still_missing = [s for s in syms if s not in result]
    if still_missing and _db_store:
        for sym in still_missing:
            for code in [sym, _WL_ALIASES.get(sym)]:
                if not code:
                    continue
                try:
                    ltp = await asyncio.to_thread(_db_ltp_fallback, code)
                    if ltp:
                        result[sym] = {"ltp": ltp, "source": "candle"}
                        break
                except Exception:
                    pass

    return result


@app.post("/api/watchlist/snapshot")
async def store_watchlist_snapshot(body: dict):
    """
    Persist a manual Breeze quote snapshot.
    Body: { prices: { SYMBOL: { ltp, prev_close } } }
    Writes into live LTP cache + spot_ticks + watchlist_state (persists prev_close).
    """
    prices = body.get("prices", {})
    if not prices:
        return {"ok": False, "message": "No prices provided."}

    ts = datetime.now(timezone.utc)
    tick_rows  = []
    state_rows = []
    for sym, data in prices.items():
        ltp = data.get("ltp")
        if ltp is None:
            continue
        sym_upper  = sym.upper()
        prev_close = data.get("prev_close")
        _ltp_cache[sym_upper] = float(ltp)
        tick_rows.append({"ts": ts, "symbol": sym_upper, "ltp": float(ltp)})
        state_rows.append({
            "ts": ts, "symbol": sym_upper,
            "ltp": float(ltp),
            "prev_close": float(prev_close) if prev_close else None,
        })

    if _db_store:
        try:
            await asyncio.to_thread(_db_store.upsert_watchlist_snapshot, tick_rows)
        except Exception as exc:
            log.warning("watchlist tick write failed: %s", exc)
        try:
            await asyncio.to_thread(_db_store.upsert_watchlist_state, state_rows)
            log.info("watchlist_state saved: %s", [r["symbol"] for r in state_rows])
        except Exception as exc:
            log.warning("watchlist state write failed: %s", exc)

    return {"ok": True, "stored": len(tick_rows)}


# ── Security master endpoints ─────────────────────────────────────────────────

@app.post("/api/data/security_master/refresh")
async def security_master_refresh():
    """Trigger an immediate security master download (runs in background thread)."""
    global _sm_running
    if _sm_running:
        return {"ok": False, "message": "Refresh already in progress."}
    db_url = os.environ.get("DB_URL", "")
    if not db_url or not _db_store:
        raise HTTPException(503, "Database not configured.")

    def _run():
        global _sm_running, _sm_status
        from collector.security_master import SecurityMasterDownloader
        _sm_running = True
        _sm_log.clear()
        _sm_status.update(status="running", error="", current="Starting…")
        try:
            def _cb(msg: str):
                _sm_log.append(msg)
                if len(_sm_log) > 200:
                    del _sm_log[0]
                _sm_status["current"] = msg[:120]
            SecurityMasterDownloader(db_url=db_url, progress_cb=_cb).run()
            _sm_status.update(status="complete", current="Done",
                              last_ok=datetime.now().isoformat(timespec="seconds"), error="")
        except Exception as exc:
            log.error("Security master manual refresh failed: %s", exc)
            _sm_status.update(status="error", current="", error=str(exc))
        finally:
            _sm_running = False

    threading.Thread(target=_run, daemon=True, name="sm-refresh").start()
    return {"ok": True, "message": "Security master refresh started."}


@app.get("/api/data/security_master/status")
async def security_master_status():
    """Return current refresh status and last-updated info."""
    stats: dict = {}
    if _db_store:
        try:
            stats = _db_store.security_master_stats()
        except Exception:
            pass
    return {
        **_sm_status,
        "running": _sm_running,
        "log": list(_sm_log[-50:]),
        "db_stats": stats,
    }


@app.get("/api/data/security_master/search")
async def security_master_search(
    q:            str = "",
    exchange:     str = "",
    product_type: str = "",
    limit:        int = 50,
):
    """
    Search security master by stock code or name.
    ?q=RELIND  ->  all rows matching RELIND
    ?q=HDFC&exchange=NSE&product_type=cash  ->  NSE cash instruments with HDFC
    """
    if not _db_store:
        raise HTTPException(503, "Database not configured.")
    limit = min(limit, 500)
    try:
        rows = _db_store.search_security_master(
            query=q, exchange=exchange, product_type=product_type, limit=limit
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"results": rows, "count": len(rows)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
