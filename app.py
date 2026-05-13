"""
app.py — Breeze Trading Dashboard (FastAPI + WebSocket)

Run:   python app.py
Open:  http://localhost:8000
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler("logs/dashboard.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("dashboard")

# ── Global state ──────────────────────────────────────────────────────────────

_session:    Optional[BreezeSession]      = None
_algo_engine: Optional[OptionsAlgoEngine] = None
_algo_task:  Optional[asyncio.Task]       = None
_poll_task:  Optional[asyncio.Task]       = None
_trigger_tasks: Dict[str, asyncio.Task]   = {}

_positions: List[dict] = []   # open + closed option/equity positions
_order_log: List[dict] = []   # every order placed this session
_ltp_cache: Dict[str, float] = {}

_MAX_DAILY_LOSS:    float = float(os.getenv("MAX_DAILY_LOSS",    "40000"))
_TOTAL_PREMIUM_CAP: float = float(os.getenv("TOTAL_PREMIUM_CAP", "78000"))

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


# ── LTP polling background task ───────────────────────────────────────────────

_POLL_NORMAL  = 10   # seconds between successful polls
_POLL_BACKOFF = 60   # seconds to wait after a 503 / parse error
_POLL_AUTH    = 300  # seconds to wait after a 401 (session likely expired)
_consecutive_errors = 0


async def _safe_get_quotes(session, **kwargs) -> Optional[dict]:
    """Call get_quotes and return the parsed response, or None on any error."""
    try:
        resp = await asyncio.to_thread(session.api.get_quotes, **kwargs)
        if isinstance(resp, dict):
            return resp
    except Exception as exc:
        log.debug("get_quotes exception: %s", exc)
    return None


async def _poll_ltps() -> None:
    global _consecutive_errors
    log.info("LTP polling started (interval=%ds).", _POLL_NORMAL)
    sleep_for = _POLL_NORMAL

    while True:
        await asyncio.sleep(sleep_for)
        sleep_for = _POLL_NORMAL   # reset; adjust below on error

        if not (_session and _session._api):
            continue

        try:
            had_error = False

            # Spot watchlist
            for w in WATCHLIST:
                resp = await _safe_get_quotes(
                    _session,
                    stock_code=w["stock"],
                    exchange_code=w["exchange"],
                    expiry_date="",
                    product_type="cash",
                    right="",
                    strike_price="",
                )
                if resp is None:
                    had_error = True
                    continue

                status = resp.get("Status")
                if status == 200 and resp.get("Success"):
                    _ltp_cache[w["stock"]] = float(resp["Success"][0]["ltp"])
                    _consecutive_errors = 0
                elif status == 5:
                    # "Limit exceed: API call per day"
                    log.warning("Breeze API daily limit hit — backing off %ds.", _POLL_AUTH)
                    await broadcast({"type": "alert",
                                     "message": "⚠ Breeze API daily call limit reached. Polling paused."})
                    sleep_for = _POLL_AUTH
                    break
                else:
                    had_error = True

            if had_error:
                _consecutive_errors += 1
                # Exponential backoff capped at 5 min
                sleep_for = min(_POLL_BACKOFF * _consecutive_errors, 300)
                log.warning("LTP poll had errors (attempt %d) — next poll in %ds.",
                            _consecutive_errors, sleep_for)
                if _consecutive_errors == 1:
                    await broadcast({"type": "alert",
                                     "message": "⚠ Breeze quote feed issue — retrying shortly."})
                continue

            # Open option legs
            for pos in list(_positions):
                if not pos.get("is_open") or pos["product"] != "options":
                    continue
                expiry_obj = date.fromisoformat(pos["expiry"])
                right_str  = "call" if pos["right"] == "CE" else "put"
                resp = await _safe_get_quotes(
                    _session,
                    stock_code=pos["stock"],
                    exchange_code=pos["exchange"],
                    expiry_date=SymbolBuilder.breeze_dt(expiry_obj),
                    product_type="options",
                    right=right_str,
                    strike_price=str(pos["strike"]),
                )
                if resp and resp.get("Status") == 200 and resp.get("Success"):
                    _ltp_cache[pos["symbol"]] = float(resp["Success"][0]["ltp"])

            _consecutive_errors = 0
            pnl_data = _compute_pnl()
            await broadcast({"type": "ltp", "data": _ltp_cache.copy()})
            await broadcast({"type": "pnl", "data": pnl_data})

            if pnl_data["total_pnl"] < -(_MAX_DAILY_LOSS * 0.80):
                await broadcast({
                    "type":    "alert",
                    "message": (
                        f"⚠ Daily loss ₹{abs(pnl_data['total_pnl']):,.0f} "
                        f"approaching limit ₹{_MAX_DAILY_LOSS:,.0f}"
                    ),
                })

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _consecutive_errors += 1
            sleep_for = min(_POLL_BACKOFF * _consecutive_errors, 300)
            log.error("LTP poll unexpected error (attempt %d, retry in %ds): %s",
                      _consecutive_errors, sleep_for, exc)


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poll_task
    _poll_task = asyncio.create_task(_poll_ltps())
    log.info("Dashboard running → http://localhost:8000")
    yield
    if _poll_task:
        _poll_task.cancel()
    for t in _trigger_tasks.values():
        t.cancel()
    if _session:
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

    kwargs: dict = dict(
        stock_code         = req.stock_code,
        exchange_code      = req.exchange_code,
        product            = req.product,
        action             = req.action,
        order_type         = req.order_type,
        stoploss           = "0",
        quantity           = str(req.quantity),
        price              = str(req.price) if req.order_type == "limit" else "0",
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
        resp = await asyncio.to_thread(_session.api.place_order, **kwargs)
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if resp.get("Status") != 200:
        raise HTTPException(400, f"Breeze rejected order: {resp}")

    order_id = resp["Success"]["order_id"]

    symbol = (
        SymbolBuilder.build(req.stock_code, expiry_obj, req.strike, req.right, "monthly")
        if req.product == "options" and req.strike and req.right
        else req.stock_code
    )

    # Use last known LTP as entry price for market orders
    entry_price = (
        req.price if req.order_type == "limit"
        else _ltp_cache.get(symbol, _ltp_cache.get(req.stock_code, 0.0))
    )

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

    log_entry = _record_order(req.action, symbol, req.quantity, entry_price, order_id)
    await broadcast({"type": "order", "data": log_entry})
    log.info("Manual order: %s %s ×%d → %s", req.action.upper(), symbol, req.quantity, order_id)
    return {"status": "placed", "order_id": order_id, "symbol": symbol}


@app.delete("/api/order/{order_id}")
async def cancel_order(order_id: str, exchange_code: str = "NFO"):
    _require_session()
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
        resp = await asyncio.to_thread(_session.api.get_portfolio_positions)
    except Exception as exc:
        return {"positions": [], "warning": str(exc)}

    if resp and resp.get("Status") == 200:
        return {"positions": resp.get("Success") or [], "warning": None}
    return {"positions": [], "warning": _breeze_error_msg(resp)}


@app.post("/api/breeze/orders/{order_id}/cancel")
async def cancel_breeze_order(order_id: str, exchange_code: str = "NFO"):
    _require_session()
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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
