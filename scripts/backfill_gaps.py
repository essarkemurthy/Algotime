#!/usr/bin/env python3
"""
Targeted gap backfill:
  1. For the 36 new stocks: fetch 1m from Jun 2 back to their current first_ts (Jun 16)
     filling the ~14-day gap caused by the 14,000-candle cap.
  2. For ALL symbols: forward gap-fill all intervals up to today (picks up May 23).
"""
import os, sys, time, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2, psycopg2.pool
from breeze_connect import BreezeConnect

LOG_FILE = ROOT / "logs" / "backfill_gaps.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# 36 new stocks (Breeze code, exchange, NSE ticker)
NEW_STOCKS = [
    ("RELIND",  "NSE", "RELIANCE"),   ("HDFBAN",  "NSE", "HDFCBANK"),
    ("INFTEC",  "NSE", "INFY"),       ("ICIBAN",  "NSE", "ICICIBANK"),
    ("HINLEV",  "NSE", "HINDUNILVR"), ("STABAN",  "NSE", "SBIN"),
    ("BHAAIR",  "NSE", "BHARTIARTL"), ("KOTMAH",  "NSE", "KOTAKBANK"),
    ("AXIBAN",  "NSE", "AXISBANK"),   ("LARTOU",  "NSE", "LT"),
    ("ASIPAI",  "NSE", "ASIANPAINT"), ("SUNPHA",  "NSE", "SUNPHARMA"),
    ("ULTCEM",  "NSE", "ULTRACEMCO"), ("NESIND",  "NSE", "NESTLEIND"),
    ("POWGRI",  "NSE", "POWERGRID"),  ("COALIN",  "NSE", "COALINDIA"),
    ("TATCOV",  "NSE", "TATAMOTORS"), ("TATSTE",  "NSE", "TATASTEEL"),
    ("HCLTEC",  "NSE", "HCLTECH"),    ("BAJFI",   "NSE", "BAJFINANCE"),
    ("DRREDD",  "NSE", "DRREDDY"),    ("BRIIND",  "NSE", "BRITANNIA"),
    ("HINDAL",  "NSE", "HINDALCO"),   ("BAFINS",  "NSE", "BAJAJFINSV"),
    ("MAHMAH",  "NSE", "M&M"),        ("BAAUTO",  "NSE", "BAJAJ-AUTO"),
    ("EICMOT",  "NSE", "EICHERMOT"),  ("HERHON",  "NSE", "HEROMOTOCO"),
    ("TITIND",  "NSE", "TITAN"),      ("ADAPOR",  "NSE", "ADANIPORTS"),
    ("JSWSTE",  "NSE", "JSWSTEEL"),   ("TECMAH",  "NSE", "TECHM"),
    ("DIVLAB",  "NSE", "DIVISLAB"),   ("INDBA",   "NSE", "INDUSINDBK"),
    ("APOHOS",  "NSE", "APOLLOHOSP"), ("BHAPET",  "NSE", "BPCL"),
]

# All 50 symbols for forward gap-fill (nse_ticker, breeze_code, exchange)
ALL_SYMBOLS = NEW_STOCKS + [
    ("NIFTY",  "NSE", "NIFTY"),   ("CNXIT",  "NSE", "CNXIT"),
    ("CIPLA",  "NSE", "CIPLA"),   ("COLPAL", "NSE", "COLPAL"),
    ("GRASIM", "NSE", "GRASIM"),  ("ITC",    "NSE", "ITC"),
    ("JIOFIN", "NSE", "JIOFIN"),  ("LUPIN",  "NSE", "LUPIN"),
    ("MARUTI", "NSE", "MARUTI"),  ("NTPC",   "NSE", "NTPC"),
    ("ONGC",   "NSE", "ONGC"),    ("TCS",    "NSE", "TCS"),
    ("TRENT",  "NSE", "TRENT"),   ("WIPRO",  "NSE", "WIPRO"),
    ("GAIL",   "NSE", "GAIL"),
]
# BIOCON and PIIND — only 1d and 30m (no 1m/5m available)
PARTIAL_SYMBOLS = [
    ("BIOCON", "NSE", "BIOCON"),
    ("PIIND",  "NSE", "PIIND"),
]

_last_call = 0.0
_call_count = 0
CALLS_PER_MINUTE = 50

def _rate_limited(fn, *args, **kwargs):
    global _last_call, _call_count
    gap = 60.0 / CALLS_PER_MINUTE
    wait = gap - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    _call_count += 1
    return fn(*args, **kwargs)

def _fmt(dt): return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def _parse_dt(raw):
    if not raw: return None
    s = str(raw)[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try: return datetime.strptime(s, fmt)
        except ValueError: continue
    return None

class Store:
    def __init__(self, url):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=url)

    def _ts(self, symbol, interval, fn):
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT {fn}(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                            (symbol, interval))
                row = cur.fetchone()
                ts = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally:
            self._pool.putconn(conn)

    def first_ts(self, sym, iv): return self._ts(sym, iv, "MIN")
    def last_ts(self,  sym, iv): return self._ts(sym, iv, "MAX")

    def insert(self, rows):
        if not rows: return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
                    VALUES (%(ts)s, %(symbol)s, %(interval)s,
                            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
                    ON CONFLICT (symbol, "interval", ts) DO NOTHING""", rows)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback(); raise
        finally:
            self._pool.putconn(conn)

    def close(self): self._pool.closeall()

def fetch_range(api, breeze_code, exchange, iv_breeze, db_iv, ticker,
                from_dt, to_dt) -> List[dict]:
    chunk = 365 if iv_breeze == "1day" else 25
    rows = []
    cursor = from_dt
    while cursor < to_dt:
        end = min(cursor + timedelta(days=chunk), to_dt)
        resp = _rate_limited(api.get_historical_data_v2,
            interval=iv_breeze, from_date=_fmt(cursor), to_date=_fmt(end),
            stock_code=breeze_code, exchange_code=exchange, product_type="cash",
            expiry_date="", right="", strike_price="")
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts: continue
                try:
                    rows.append({"ts": ts, "symbol": ticker, "interval": db_iv,
                        "open": float(raw["open"]),  "high": float(raw["high"]),
                        "low":  float(raw["low"]),   "close": float(raw["close"]),
                        "volume": int(float(raw.get("volume", 0) or 0))})
                except (KeyError, TypeError, ValueError):
                    pass
        cursor = end + timedelta(days=1)
    return rows

def main():
    log.info("=" * 70)
    log.info("BACKFILL GAPS — 1m backward fill + May23 forward fill")
    log.info("=" * 70)

    store = Store(os.environ["DB_URL"])
    api = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                         session_token=os.environ["BREEZE_SESSION_TOKEN"])
    log.info("Breeze session OK")

    today   = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    # Target start for 1m backfill — match the earliest existing 1m start (Jun 2 2025)
    one_m_target = datetime(2025, 6, 2, 0, 0, 0)
    total_new = 0

    # ── Phase 1: backfill 1m gap for 36 new stocks (Jun 2 → Jun 16) ──────────
    log.info("\n-- Phase 1: 1m backward fill for 36 new stocks --")
    for breeze_code, exchange, ticker in NEW_STOCKS:
        first = store.first_ts(ticker, "1m")
        if first is None:
            log.info("  %-14s  no 1m data at all — skip", ticker)
            continue
        first = first.replace(tzinfo=None) if hasattr(first, 'tzinfo') else first
        if first <= one_m_target + timedelta(days=1):
            log.info("  %-14s  1m starts %s — already OK", ticker, first.date())
            continue
        # Gap exists: fetch from target up to first-1min
        gap_end = first - timedelta(minutes=1)
        log.info("  %-14s  filling 1m  %s -> %s  (calls: %d)",
                 ticker, one_m_target.date(), gap_end.date(), _call_count)
        rows = fetch_range(api, breeze_code, exchange, "1minute", "1m",
                           ticker, one_m_target, gap_end)
        if rows:
            store.insert(rows)
            total_new += len(rows)
            log.info("    +%d candles  (total calls: %d)", len(rows), _call_count)
        else:
            log.info("    0 candles returned")

    log.info("Phase 1 done.  New: %d  Calls: %d", total_new, _call_count)

    # ── Phase 2: forward gap-fill ALL symbols, all intervals, up to today ────
    log.info("\n-- Phase 2: forward gap-fill all symbols to today (May 23) --")
    p2_new = 0
    intervals = [
        ("1day",    "1d"),
        ("30minute","30m"),
        ("5minute", "5m"),
        ("1minute", "1m"),
    ]
    partial_ivs = [("1day","1d"), ("30minute","30m")]

    all_to_fill = [(bc, ex, tk, intervals) for bc, ex, tk in ALL_SYMBOLS]
    all_to_fill += [(bc, ex, tk, partial_ivs) for bc, ex, tk in PARTIAL_SYMBOLS]

    for breeze_code, exchange, ticker, ivs in all_to_fill:
        for iv_breeze, iv_db in ivs:
            last = store.last_ts(ticker, iv_db)
            if last is None:
                continue
            last = last.replace(tzinfo=None) if hasattr(last, 'tzinfo') else last
            fetch_from = last + timedelta(minutes=1)
            if fetch_from >= today - timedelta(hours=1):
                continue  # already up to date
            log.info("  %-14s [%s]  forward: %s -> %s",
                     ticker, iv_db, fetch_from.date(), today.date())
            rows = fetch_range(api, breeze_code, exchange, iv_breeze, iv_db,
                               ticker, fetch_from, today)
            if rows:
                store.insert(rows)
                p2_new += len(rows)
                total_new += len(rows)
                log.info("    +%d candles  (calls: %d)", len(rows), _call_count)

    log.info("Phase 2 done.  New: %d  Calls: %d", p2_new, _call_count)
    log.info("=" * 70)
    log.info("DONE.  Total new: %d  Total calls: %d", total_new, _call_count)
    log.info("=" * 70)
    store.close()

if __name__ == "__main__":
    main()
