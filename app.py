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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
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


class BreezeRateLimiter:
    """Thread-safe sliding-window rate limiter for Breeze REST calls.
    Enforces 75 calls/minute and 4,500 calls/day (safe margins below ICICI limits)."""

    def __init__(self, per_min: int = 75, per_day: int = 4500) -> None:
        self._per_min   = per_min
        self._per_day   = per_day
        self._minute_q  = deque()
        self._day_count = 0
        self._day_reset = time.monotonic()
        self._lock      = threading.Lock()

    def acquire(self, label: str = "api") -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._day_reset > 86400:
                self._day_count = 0
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
                "calls_today":      self._day_count,
                "calls_this_min":   len(self._minute_q),
                "day_limit":        self._per_day,
                "min_limit":        self._per_min,
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

# ── Global state ──────────────────────────────────────────────────────────────

_session:    Optional[BreezeSession]      = None
_algo_engine: Optional[OptionsAlgoEngine] = None
_algo_task:  Optional[asyncio.Task]       = None
_broadcast_task: Optional[asyncio.Task]   = None
_chain_snap_task: Optional[asyncio.Task]  = None   # periodic chain/delta snapshots
_trigger_tasks: Dict[str, asyncio.Task]   = {}
_main_loop:  Optional[asyncio.AbstractEventLoop] = None

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

_MAX_DAILY_LOSS:    float = float(os.getenv("MAX_DAILY_LOSS",    "40000"))
_TOTAL_PREMIUM_CAP: float = float(os.getenv("TOTAL_PREMIUM_CAP", "78000"))

# ── DB store (optional — graceful degradation when PostgreSQL not configured) ──
_db_store = None   # collector.store.DataStore | None

def _init_db_store() -> None:
    global _db_store
    db_url = os.getenv("DB_URL", "")
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
    {"stock": "NIFTY",     "exchange": "NSE", "label": "NIFTY"},
    {"stock": "INFY",      "exchange": "NSE", "label": "INFY"},
    {"stock": "ONGC",      "exchange": "NSE", "label": "ONGC"},
    {"stock": "MAXHEALTH", "exchange": "NSE", "label": "MAXHEALTH"},
]

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
    _ltp_cache[cache_key] = ltp_f

    now = datetime.now()

    # ── Buffer tick for DB persistence ────────────────────────────────────────
    if _db_store is not None:
        with _tick_buffer_lock:
            _tick_buffer.append({
                "ts":     now,
                "symbol": cache_key,
                "ltp":    ltp_f,
                "volume": int(tick.get("ltq", 0) or 0),
            })

    # ── Build tick entry for the live tick pane ───────────────────────────────
    entry = {
        "t":      now.strftime("%H:%M:%S"),
        "ltp":    ltp_f,
        "change": float(tick.get("change", 0) or 0),
        "bid":    float(tick.get("bPrice", 0) or 0),
        "ask":    float(tick.get("sPrice", 0) or 0),
        "ltq":    int(tick.get("ltq", 0) or 0),
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

        # Store token → cache_key mapping so _on_tick can route ticks correctly
        _token_to_symbol[eq_token] = cache_key or stock
        _ws_subscriptions.add(sub_key)
        log.info("WS subscribed: %s → token %s", cache_key or stock, eq_token)
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
    """Open Breeze WebSocket and subscribe watchlist + any existing option legs.
    Must be called in a thread (blocking SDK calls)."""
    _session.api.on_ticks = _on_tick
    _session.api.ws_connect()
    for w in WATCHLIST:
        _ws_subscribe(w["stock"], w["exchange"], cache_key=w["stock"])
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


# ── Symbol index ──────────────────────────────────────────────────────────────

# Exchange index within token_script_dict_list
_EXCH_IDX = {0: "BSE", 1: "NSE", 2: "NDX", 3: "MCX", 4: "NFO", 5: "BFO"}


def _build_symbol_index() -> None:
    """Extract symbols from the SDK's in-memory security master.

    NSE/BSE equity  → one entry per stock_code, token preserved.
    NFO/BFO/MCX/NDX → deduplicated to one entry per (underlying, exchange, product_type)
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
        log.info("Symbol index saved → %s", _SYMBOL_CACHE)
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


async def _chain_snapshot_loop() -> None:
    """Every CHAIN_SNAP_SEC, fetch full option chains + PCR and persist to DB."""
    await asyncio.sleep(60)   # give connection 60 s to settle before first run
    while True:
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


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _broadcast_task, _chain_snap_task, _main_loop
    _main_loop      = asyncio.get_event_loop()
    _broadcast_task = asyncio.create_task(_broadcast_loop())
    _chain_snap_task = asyncio.create_task(_chain_snapshot_loop())
    _load_symbol_index()
    _init_db_store()   # connect to PostgreSQL if DB_URL is set
    # Start background tick writer thread (no-op if DB unavailable)
    threading.Thread(target=_tick_writer_thread, daemon=True, name="tick-writer").start()
    log.info("Dashboard running → http://localhost:8000")
    yield
    if _broadcast_task:
        _broadcast_task.cancel()
    if _chain_snap_task:
        _chain_snap_task.cancel()
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
    return {
        "connected":    bool(_session and _session._api),
        "algo_running": bool(_algo_task and not _algo_task.done()),
    }


# ── Manual order ──────────────────────────────────────────────────────────────

@app.post("/api/order/manual")
async def place_manual_order(req: ManualOrderReq):
    _require_session()

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
    log.info("Manual order: %s %s ×%d → %s", req.action.upper(), symbol, req.quantity, order_id)
    return {"status": "placed", "order_id": order_id, "symbol": symbol}


@app.delete("/api/order/{order_id}")
async def cancel_order(order_id: str, exchange_code: str = "NFO"):
    _require_session()
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
    err = resp.get("Error", "")
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
        "message": f"RESEARCH → TRIGGER: {call['stock_code']} {call['recommendation']} @ ₹{trigger:,.2f}",
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

    # Auto-register as a trigger order (requires an active session)
    trigger_key = None
    if _session and _session._api:
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
    try:
        order = _paper.exit_position(pos_id, _ltp_cache)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    summary = _paper.summary(_ltp_cache)
    await broadcast({"type": "paper_update", "data": summary})
    return {"order": _paper._order_dict(order), "summary": summary}


@app.get("/api/paper/summary")
async def paper_summary():
    return _paper.summary(_ltp_cache)


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
        # Any word is a code prefix → match
        if any(code.startswith(w) for w in words):
            return True
        # All words appear somewhere in the name → match
        if all(w in name or w in code for w in words):
            return True
        # Single long word is a substring of the name → match
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
                       f"Available symbols: NIFTY, MARUTI, TCS, WIPRO, NTPC, ONGC",
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

    # Pre-calculate total work items so ETA is available from the first poll
    from collector.config import CollectorConfig as _Cfg
    _tmp = _Cfg(
        api_key=api_key, api_secret=api_secret,
        session_token=session_token, db_url=db_url,
        backfill_days=backfill_days, backfill_days_daily=backfill_days_daily,
    )
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
