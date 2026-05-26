#!/usr/bin/env python3
"""
scripts/extend_history.py — Use remaining Breeze calls to:
  1. Push daily history back as far as Breeze allows (~10+ years) for
     the 17 symbols already confirmed to return data.
  2. Re-test zero-return Nifty50 stocks with BSE exchange (some may
     have data there even though NSE returned nothing).
  3. Re-test with product_type="others" for stocks that returned 0.

Run once to exhaust remaining quota for today.
"""

import os, sys, time, logging, json
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import List, Tuple, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import psycopg2
import psycopg2.pool
from breeze_connect import BreezeConnect

IST = timezone(timedelta(hours=5, minutes=30))

LOG_FILE = ROOT / "logs" / "extend_history.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Symbols confirmed to return data ─────────────────────────────────────────
KNOWN_SYMBOLS = [
    ("NIFTY",  "NSE"), ("CNXIT",  "NSE"),
    ("CIPLA",  "NSE"), ("COLPAL", "NSE"), ("GRASIM", "NSE"),
    ("ITC",    "NSE"), ("JIOFIN", "NSE"), ("LUPIN",  "NSE"),
    ("MARUTI", "NSE"), ("NTPC",   "NSE"), ("ONGC",   "NSE"),
    ("TCS",    "NSE"), ("TRENT",  "NSE"), ("WIPRO",  "NSE"),
    ("BIOCON", "NSE"), ("PIIND",  "NSE"), ("GAIL",   "NSE"),
]

# ── Nifty50 stocks that returned 0 from NSE/cash — try BSE ───────────────────
NSE_ZERO_TRY_BSE = [
    ("RELIANCE",    "BSE"), ("HDFCBANK",  "BSE"), ("INFY",       "BSE"),
    ("ICICIBANK",   "BSE"), ("HINDUNILVR","BSE"), ("SBIN",       "BSE"),
    ("BHARTIARTL",  "BSE"), ("KOTAKBANK", "BSE"), ("AXISBANK",   "BSE"),
    ("LT",          "BSE"), ("ASIANPAINT","BSE"), ("SUNPHARMA",  "BSE"),
    ("ULTRACEMCO",  "BSE"), ("NESTLEIND", "BSE"), ("POWERGRID",  "BSE"),
    ("COALINDIA",   "BSE"), ("TATAMOTORS","BSE"), ("TATASTEEL",  "BSE"),
    ("HCLTECH",     "BSE"), ("BAJFINANCE","BSE"), ("DRREDDY",    "BSE"),
    ("BRITANNIA",   "BSE"), ("HINDALCO",  "BSE"), ("BAJAJFINSV", "BSE"),
]

# ── Rate limiter (simple) ─────────────────────────────────────────────────────
_last_call = 0.0
_call_count = 0
CALLS_PER_MINUTE = 50   # conservative
MAX_CALLS = 1800        # hard cap for this session

def _rate_limited_call(fn, *args, **kwargs):
    global _last_call, _call_count
    if _call_count >= MAX_CALLS:
        raise RuntimeError(f"Session cap reached ({MAX_CALLS} calls)")
    gap = 60.0 / CALLS_PER_MINUTE
    wait = gap - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    _call_count += 1
    return fn(*args, **kwargs)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_dt(raw) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw)[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────

class Store:
    def __init__(self, url: str):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=url)

    def first_ts(self, symbol: str, interval: str) -> Optional[datetime]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MIN(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                    (symbol, interval))
                row = cur.fetchone()
                ts = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally:
            self._pool.putconn(conn)

    def last_ts(self, symbol: str, interval: str) -> Optional[datetime]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MAX(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                    (symbol, interval))
                row = cur.fetchone()
                ts = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally:
            self._pool.putconn(conn)

    def insert(self, rows: list) -> int:
        if not rows:
            return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO candles
                       (ts, symbol, "interval", open, high, low, close, volume)
                       VALUES (%(ts)s, %(symbol)s, %(interval)s,
                               %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
                       ON CONFLICT (symbol, "interval", ts) DO NOTHING""",
                    rows)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()


def fetch_range(api, symbol: str, exchange: str, interval: str,
                from_dt: datetime, to_dt: datetime,
                product_type: str = "cash") -> List[dict]:
    rows = []
    chunk = 365 if interval == "1day" else 25
    cursor = from_dt
    while cursor < to_dt:
        end = min(cursor + timedelta(days=chunk), to_dt)
        resp = _rate_limited_call(
            api.get_historical_data_v2,
            interval=interval,
            from_date=_fmt(cursor),
            to_date=_fmt(end),
            stock_code=symbol,
            exchange_code=exchange,
            product_type=product_type,
            expiry_date="", right="", strike_price="",
        )
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts:
                    continue
                try:
                    rows.append({
                        "ts": ts, "symbol": symbol, "interval": "1d",
                        "open": float(raw["open"]), "high": float(raw["high"]),
                        "low":  float(raw["low"]),  "close": float(raw["close"]),
                        "volume": int(float(raw.get("volume", 0) or 0)),
                    })
                except (KeyError, TypeError, ValueError):
                    pass
        cursor = end + timedelta(days=1)
    return rows


def main():
    log.info("=" * 65)
    log.info("EXTEND HISTORY  — pushing daily candles back as far as possible")
    log.info("=" * 65)

    store = Store(os.environ["DB_URL"])
    api   = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(
        api_secret    = os.environ["BREEZE_API_SECRET"],
        session_token = os.environ["BREEZE_SESSION_TOKEN"],
    )
    log.info("Breeze session OK.  Session call cap: %d", MAX_CALLS)

    today   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    far_ago = today - timedelta(days=5000)   # ~13.7 years back

    total_new = 0

    # ── Phase A: extend daily for known symbols ───────────────────────────────
    log.info("\n-- Phase A: extend daily history back to ~2011 for known symbols --")
    for symbol, exchange in KNOWN_SYMBOLS:
        first = store.first_ts(symbol, "1d")
        if first is None:
            log.info("  %-16s  no 1d data in DB — skipping", symbol)
            continue
        if first <= far_ago + timedelta(days=5):
            log.info("  %-16s  already at %s — up to date", symbol, first.date())
            continue

        fetch_to   = first - timedelta(days=1)
        fetch_from = far_ago
        log.info("  %-16s  extending from %s back to %s",
                 symbol, first.date(), fetch_from.date())
        try:
            rows = fetch_range(api, symbol, exchange, "1day", fetch_from, fetch_to)
            if rows:
                store.insert(rows)
                log.info("    +%d daily candles  (calls so far: %d)", len(rows), _call_count)
                total_new += len(rows)
            else:
                log.info("    +0 candles (Breeze limit at %s)", first.date())
        except RuntimeError:
            log.warning("Session call cap reached — stopping Phase A.")
            break
        except Exception as e:
            log.error("  ERROR %s: %s", symbol, e)

    log.info("Phase A done.  New candles: %d  Calls used: %d", total_new, _call_count)

    # ── Phase B: test zero-return Nifty50 stocks via BSE exchange ─────────────
    log.info("\n-- Phase B: test NSE-zero stocks on BSE (daily, 2 years) --")
    test_from = today - timedelta(days=730)
    b_new = 0
    for symbol, exchange in NSE_ZERO_TRY_BSE:
        # Already have NSE data? skip
        if store.last_ts(symbol, "1d"):
            log.debug("  %-16s  already has 1d data — skip BSE test", symbol)
            continue
        try:
            rows = fetch_range(api, symbol, exchange, "1day", test_from, today)
            if rows:
                # Fix symbol in rows (use same symbol name)
                store.insert(rows)
                log.info("  %-16s [BSE]  +%d candles  (calls: %d)",
                         symbol, len(rows), _call_count)
                b_new += total_new
                total_new += len(rows)
            else:
                log.info("  %-16s [BSE]  0 candles", symbol)
        except RuntimeError:
            log.warning("Session call cap reached — stopping Phase B.")
            break
        except Exception as e:
            log.error("  ERROR %s: %s", symbol, e)

    log.info("Phase B done.  New candles: %d  Calls used: %d", total_new, _call_count)

    # ── Final summary ─────────────────────────────────────────────────────────
    log.info("=" * 65)
    log.info("DONE.  Total new candles: %d  Total API calls: %d", total_new, _call_count)
    log.info("=" * 65)
    store.close()


if __name__ == "__main__":
    main()
