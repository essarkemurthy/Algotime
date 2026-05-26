#!/usr/bin/env python3
"""
scripts/download_nifty50.py — Download daily + intraday history for all Nifty50
stocks using correct Breeze stock_codes from the master file (symbols.json).

Usage:
  python scripts/download_nifty50.py               # 1day only, all 50
  python scripts/download_nifty50.py --intraday     # also 5min + 1min (many calls)
  python scripts/download_nifty50.py --max-calls 500
  python scripts/download_nifty50.py --dry-run      # print plan, no API calls
"""

import os, sys, time, logging, argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

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

IST_OFFSET = timedelta(hours=5, minutes=30)
LOG_FILE = ROOT / "logs" / "download_nifty50.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Nifty50 mapping: NSE ticker -> Breeze stock_code ─────────────────────────
# Source: symbols.json (ICICI Direct master file)
NIFTY50 = [
    # NSE_ticker      Breeze_code   Exchange
    ("RELIANCE",      "RELIND",     "NSE"),
    ("HDFCBANK",      "HDFBAN",     "NSE"),
    ("INFY",          "INFTEC",     "NSE"),
    ("ICICIBANK",     "ICIBAN",     "NSE"),
    ("HINDUNILVR",    "HINLEV",     "NSE"),
    ("SBIN",          "STABAN",     "NSE"),
    ("BHARTIARTL",    "BHAAIR",     "NSE"),
    ("KOTAKBANK",     "KOTMAH",     "NSE"),
    ("AXISBANK",      "AXIBAN",     "NSE"),
    ("LT",            "LARTOU",     "NSE"),
    ("ASIANPAINT",    "ASIPAI",     "NSE"),
    ("SUNPHARMA",     "SUNPHA",     "NSE"),
    ("ULTRACEMCO",    "ULTCEM",     "NSE"),
    ("NESTLEIND",     "NESIND",     "NSE"),
    ("POWERGRID",     "POWGRI",     "NSE"),
    ("COALINDIA",     "COALIN",     "NSE"),
    ("TATAMOTORS",    "TATCOV",     "NSE"),
    ("TATASTEEL",     "TATSTE",     "NSE"),
    ("HCLTECH",       "HCLTEC",     "NSE"),
    ("BAJFINANCE",    "BAJFI",      "NSE"),
    ("DRREDDY",       "DRREDD",     "NSE"),
    ("BRITANNIA",     "BRIIND",     "NSE"),
    ("HINDALCO",      "HINDAL",     "NSE"),
    ("BAJAJFINSV",    "BAFINS",     "NSE"),
    ("M&M",           "MAHMAH",     "NSE"),
    ("BAJAJ-AUTO",    "BAAUTO",     "NSE"),
    ("EICHERMOT",     "EICMOT",     "NSE"),
    ("HEROMOTOCO",    "HERHON",     "NSE"),
    ("TITAN",         "TITIND",     "NSE"),
    ("ADANIPORTS",    "ADAPOR",     "NSE"),
    ("JSWSTEEL",      "JSWSTE",     "NSE"),
    ("TECHM",         "TECMAH",     "NSE"),
    ("DIVISLAB",      "DIVLAB",     "NSE"),
    ("INDUSINDBK",    "INDBA",      "NSE"),
    ("APOLLOHOSP",    "APOHOS",     "NSE"),
    ("BPCL",          "BHAPET",     "NSE"),
    # Already working — skip if in DB, but include for gap-fill
    ("NIFTY",         "NIFTY",      "NSE"),
    ("CNXIT",         "CNXIT",      "NSE"),
    ("CIPLA",         "CIPLA",      "NSE"),
    ("COLPAL",        "COLPAL",     "NSE"),
    ("GRASIM",        "GRASIM",     "NSE"),
    ("ITC",           "ITC",        "NSE"),
    ("JIOFIN",        "JIOFIN",     "NSE"),
    ("LUPIN",         "LUPIN",      "NSE"),
    ("MARUTI",        "MARUTI",     "NSE"),
    ("NTPC",          "NTPC",       "NSE"),
    ("ONGC",          "ONGC",       "NSE"),
    ("TCS",           "TCS",        "NSE"),
    ("TRENT",         "TRENT",      "NSE"),
    ("WIPRO",         "WIPRO",      "NSE"),
    ("GAIL",          "GAIL",       "NSE"),
]

# ── Rate limiter ──────────────────────────────────────────────────────────────
_last_call = 0.0
_call_count = 0
CALLS_PER_MINUTE = 50


def _rate_limited_call(fn, *args, **kwargs):
    global _last_call, _call_count
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


# ── DB store ──────────────────────────────────────────────────────────────────
class Store:
    def __init__(self, url: str):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=url)

    def _ts(self, symbol: str, interval: str, fn: str) -> Optional[datetime]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {fn}(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                    (symbol, interval))
                row = cur.fetchone()
                ts = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally:
            self._pool.putconn(conn)

    def first_ts(self, symbol, interval): return self._ts(symbol, interval, "MIN")
    def last_ts(self,  symbol, interval): return self._ts(symbol, interval, "MAX")

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


# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_range(api, breeze_code: str, exchange: str, interval: str,
                db_interval: str, nse_ticker: str,
                from_dt: datetime, to_dt: datetime) -> List[dict]:
    chunk = 365 if interval == "1day" else 25
    rows = []
    cursor = from_dt
    while cursor < to_dt:
        end = min(cursor + timedelta(days=chunk), to_dt)
        resp = _rate_limited_call(
            api.get_historical_data_v2,
            interval=interval,
            from_date=_fmt(cursor),
            to_date=_fmt(end),
            stock_code=breeze_code,
            exchange_code=exchange,
            product_type="cash",
            expiry_date="", right="", strike_price="",
        )
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts:
                    continue
                try:
                    rows.append({
                        "ts": ts, "symbol": nse_ticker, "interval": db_interval,
                        "open":   float(raw["open"]),  "high":  float(raw["high"]),
                        "low":    float(raw["low"]),   "close": float(raw["close"]),
                        "volume": int(float(raw.get("volume", 0) or 0)),
                    })
                except (KeyError, TypeError, ValueError):
                    pass
        cursor = end + timedelta(days=1)
    return rows


def download_symbol(api, store, nse_ticker, breeze_code, exchange,
                    interval, db_interval, from_dt, to_dt, dry_run=False):
    """Download with backward + forward gap fill. Returns (new_candles, calls_used)."""
    calls_before = _call_count
    total_new = 0

    # Backward gap
    first = store.first_ts(nse_ticker, db_interval)
    if first and first > from_dt + timedelta(days=1):
        bwd_end = first - timedelta(days=1)
        log.info("    backward: %s -> %s", from_dt.date(), bwd_end.date())
        if not dry_run:
            rows = fetch_range(api, breeze_code, exchange, interval, db_interval,
                               nse_ticker, from_dt, bwd_end)
            if rows:
                store.insert(rows)
                total_new += len(rows)
                log.info("      +%d candles", len(rows))

    # Forward gap
    last = store.last_ts(nse_ticker, db_interval)
    fetch_from = (last + timedelta(minutes=1)) if last else from_dt
    fetch_from = max(fetch_from, from_dt)
    if fetch_from < to_dt - timedelta(hours=1):
        log.info("    forward: %s -> %s", fetch_from.date(), to_dt.date())
        if not dry_run:
            rows = fetch_range(api, breeze_code, exchange, interval, db_interval,
                               nse_ticker, fetch_from, to_dt)
            if rows:
                store.insert(rows)
                total_new += len(rows)
                log.info("      +%d candles", len(rows))
    elif last and fetch_from >= to_dt - timedelta(hours=1):
        log.info("    up to date (last: %s)", last.date())

    return total_new, _call_count - calls_before


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intraday", action="store_true",
                   help="Also download 5minute and 1minute data")
    p.add_argument("--max-calls", type=int, default=2000,
                   help="Stop after N API calls (default 2000)")
    p.add_argument("--days", type=int, default=5000,
                   help="How many days back to fetch (default 5000 = ~13.7 years for 1day)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without making API calls")
    args = p.parse_args()

    log.info("=" * 70)
    log.info("NIFTY50 DOWNLOAD  (breeze stock_codes from master file)")
    log.info("max_calls=%d  intraday=%s  days=%d  dry_run=%s",
             args.max_calls, args.intraday, args.days, args.dry_run)
    log.info("=" * 70)

    store = Store(os.environ["DB_URL"])

    if not args.dry_run:
        api = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
        api.generate_session(
            api_secret=os.environ["BREEZE_API_SECRET"],
            session_token=os.environ["BREEZE_SESSION_TOKEN"],
        )
        log.info("Breeze session OK")
    else:
        api = None
        log.info("DRY RUN — no API calls")

    today = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    far_ago = today - timedelta(days=args.days)
    intraday_from = today - timedelta(days=365)   # 1 year for intraday

    # Intervals to download
    intervals = [("1day", "1d", far_ago)]
    if args.intraday:
        intervals += [
            ("30minute", "30m", intraday_from),
            ("5minute",  "5m",  intraday_from),
            ("1minute",  "1m",  intraday_from),
        ]

    total_new = 0
    stop = False

    for iv_breeze, iv_db, iv_from in intervals:
        if stop:
            break
        log.info("\n-- Interval: %s (db: %s) --", iv_breeze, iv_db)

        for nse_ticker, breeze_code, exchange in NIFTY50:
            if _call_count >= args.max_calls:
                log.warning("Reached max_calls=%d — stopping.", args.max_calls)
                stop = True
                break

            log.info("  %-14s [%s -> %s]", nse_ticker, breeze_code, iv_breeze)
            try:
                new, calls = download_symbol(
                    api, store, nse_ticker, breeze_code, exchange,
                    iv_breeze, iv_db, iv_from, today, dry_run=args.dry_run
                )
                total_new += new
                log.info("    done: +%d candles, %d calls (total: %d/%d)",
                         new, calls, _call_count, args.max_calls)
            except Exception as e:
                log.error("  ERROR %s: %s", nse_ticker, e)

    log.info("=" * 70)
    log.info("DONE.  Total new candles: %d  Total API calls: %d", total_new, _call_count)
    log.info("=" * 70)
    store.close()


if __name__ == "__main__":
    main()
