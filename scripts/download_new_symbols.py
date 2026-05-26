#!/usr/bin/env python3
"""
Download daily + intraday history for:
  - 9 NSE indices (BANKNIFTY, NIFTY NEXT 50, MIDCAP50, etc.)
  - 48 Nifty Next 50 stocks
  - 20 other midcap/notable stocks
Total: ~77 new symbols
"""
import os, sys, time, logging, argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2, psycopg2.pool
from breeze_connect import BreezeConnect

LOG_FILE = ROOT / "logs" / "download_new_symbols.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# (breeze_code, exchange, nse_ticker/label)
SYMBOLS = [
    # ── NSE Indices ────────────────────────────────────────────────────────────
    ("CNXBAN", "NSE", "BANKNIFTY"),
    ("NIFNEX", "NSE", "NIFTYNEXT50"),
    ("NIFMID", "NSE", "NIFTYMIDCAP50"),
    ("NIFFIN", "NSE", "NIFTYFINSERV"),
    ("NIFSEL", "NSE", "NIFTYMIDSELECT"),
    ("CNXINF", "NSE", "NIFTYINFRA"),
    ("CNXPSE", "NSE", "NIFTYPSE"),
    ("CNXNIF", "NSE", "NIFTYJR"),
    ("INDVIX", "NSE", "INDIAVIX"),

    # ── Nifty Next 50 stocks ───────────────────────────────────────────────────
    ("ADAENT", "NSE", "ADANIENT"),
    ("ADAGRE", "NSE", "ADANIGREEN"),
    ("ADAPOW", "NSE", "ADANIPOWER"),
    ("AMBCE",  "NSE", "AMBUJACEM"),
    ("ABB",    "NSE", "ABB"),
    ("ADAGAS", "NSE", "ATGL"),
    ("BAJHOU", "NSE", "BAJAJHFL"),
    ("BANBAR", "NSE", "BANKBARODA"),
    ("BHAELE", "NSE", "BEL"),
    ("BHEL",   "NSE", "BHEL"),
    ("BOSLIM", "NSE", "BOSCHLTD"),
    ("CANBAN", "NSE", "CANBK"),
    ("CHOINV", "NSE", "CHOLAFIN"),
    ("CONCOR", "NSE", "CONCOR"),
    ("DABIND", "NSE", "DABUR"),
    ("DLFLIM", "NSE", "DLF"),
    ("AVESUP", "NSE", "DMART"),
    ("FEDBAN", "NSE", "FEDERALBNK"),
    ("GODCON", "NSE", "GODREJCP"),
    ("HAVIND", "NSE", "HAVELLS"),
    ("HDFSTA", "NSE", "HDFCLIFE"),
    ("HINPET", "NSE", "HINDPETRO"),
    ("ICILOM", "NSE", "ICICIGI"),
    ("ICIPRU", "NSE", "ICICIPRULI"),
    ("INDOIL", "NSE", "IOC"),
    ("INDRAI", "NSE", "IRCTC"),
    ("JINSP",  "NSE", "JINDALSTEL"),
    ("UNISPI", "NSE", "MCDOWELL-N"),
    ("MOTSUM", "NSE", "MOTHERSON"),
    ("MUTFIN", "NSE", "MUTHOOTFIN"),
    ("INFEDG", "NSE", "NAUKRI"),
    ("NHPC",   "NSE", "NHPC"),
    ("NATMIN", "NSE", "NMDC"),
    ("PIDIND", "NSE", "PIDILITIND"),
    ("RURELE", "NSE", "RECLTD"),
    ("SAIL",   "NSE", "SAIL"),
    ("SHRTRA", "NSE", "SHRIRAMFIN"),
    ("SIEMEN", "NSE", "SIEMENS"),
    ("SRF",    "NSE", "SRF"),
    ("TATCOM", "NSE", "TATACOMM"),
    ("TATPOW", "NSE", "TATAPOWER"),
    ("TORPHA", "NSE", "TORNTPHARM"),
    ("TVSMOT", "NSE", "TVSMOTOR"),
    ("UNIP",   "NSE", "UPL"),
    ("VARBEV", "NSE", "VBL"),
    ("VEDLIM", "NSE", "VEDL"),
    ("ZOMLIM", "NSE", "ZOMATO"),
    ("CADHEA", "NSE", "ZYDUSLIFE"),

    # ── Other notable midcap/IT/FMCG ─────────────────────────────────────────
    ("PERSYS", "NSE", "PERSISTENT"),
    ("MPHLIM", "NSE", "MPHASIS"),
    ("NIITEC", "NSE", "COFORGE"),
    ("KPITE",  "NSE", "KPIT"),
    ("LTTEC",  "NSE", "LTTS"),
    ("MARLIM", "NSE", "MARICO"),
    ("BERPAI", "NSE", "BERGEPAINT"),
    ("VOLTAS", "NSE", "VOLTAS"),
    ("RADKHA", "NSE", "RADICO"),
    ("MANAFI", "NSE", "MANAPPURAM"),
    ("IDFBAN", "NSE", "IDFCFIRSTB"),
    ("HINZIN", "NSE", "HINDZINC"),
    ("MOILIM", "NSE", "MOIL"),
    ("GODPRO", "NSE", "GODREJPROP"),
    ("OBEREA", "NSE", "OBEROIRLTY"),
    ("PREEST", "NSE", "PRESTIGE"),
]

# ── Rate limiter ──────────────────────────────────────────────────────────────
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

    def _ts(self, sym, iv, fn):
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT {fn}(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                            (sym, iv))
                row = cur.fetchone()
                ts = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally:
            self._pool.putconn(conn)

    def first_ts(self, s, i): return self._ts(s, i, "MIN")
    def last_ts(self,  s, i): return self._ts(s, i, "MAX")

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

def fetch_range(api, bcode, exch, iv_api, iv_db, ticker, from_dt, to_dt):
    chunk = 365 if iv_api == "1day" else 25
    rows, cursor = [], from_dt
    while cursor < to_dt:
        end = min(cursor + timedelta(days=chunk), to_dt)
        resp = _rate_limited(api.get_historical_data_v2,
            interval=iv_api, from_date=_fmt(cursor), to_date=_fmt(end),
            stock_code=bcode, exchange_code=exch, product_type="cash",
            expiry_date="", right="", strike_price="")
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts: continue
                try:
                    rows.append({"ts": ts, "symbol": ticker, "interval": iv_db,
                        "open":  float(raw["open"]),  "high": float(raw["high"]),
                        "low":   float(raw["low"]),   "close":float(raw["close"]),
                        "volume":int(float(raw.get("volume", 0) or 0))})
                except (KeyError, TypeError, ValueError): pass
        cursor = end + timedelta(days=1)
    return rows

def download_one(api, store, bcode, exch, ticker, iv_api, iv_db, from_dt, to_dt, max_calls):
    new = 0
    # backward gap
    first = store.first_ts(ticker, iv_db)
    if first and first > from_dt + timedelta(days=1):
        rows = fetch_range(api, bcode, exch, iv_api, iv_db, ticker, from_dt, first - timedelta(days=1))
        if rows:
            store.insert(rows); new += len(rows)
            log.info("    bwd +%d  (calls %d/%d)", len(rows), _call_count, max_calls)
    # forward gap
    last = store.last_ts(ticker, iv_db)
    fetch_from = (last + timedelta(minutes=1)) if last else from_dt
    fetch_from = max(fetch_from, from_dt)
    if fetch_from < to_dt - timedelta(hours=1):
        rows = fetch_range(api, bcode, exch, iv_api, iv_db, ticker, fetch_from, to_dt)
        if rows:
            store.insert(rows); new += len(rows)
            log.info("    fwd +%d  (calls %d/%d)", len(rows), _call_count, max_calls)
        elif not last:
            log.info("    0 candles — Breeze may not have data for this code")
    else:
        log.info("    up to date")
    return new

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=3000)
    ap.add_argument("--days",      type=int, default=5000,  help="1d history depth")
    ap.add_argument("--idays",     type=int, default=365,   help="intraday history depth")
    ap.add_argument("--no-intraday", action="store_true")
    args = ap.parse_args()

    log.info("=" * 70)
    log.info("DOWNLOAD NEW SYMBOLS  (%d symbols, max_calls=%d)", len(SYMBOLS), args.max_calls)
    log.info("=" * 70)

    store = Store(os.environ["DB_URL"])
    api   = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                         session_token=os.environ["BREEZE_SESSION_TOKEN"])
    log.info("Breeze session OK")

    today        = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    far_ago      = today - timedelta(days=args.days)
    intraday_from= today - timedelta(days=args.idays)

    intervals = [("1day","1d",far_ago)]
    if not args.no_intraday:
        intervals += [
            ("30minute","30m", intraday_from),
            ("5minute", "5m",  intraday_from),
            ("1minute", "1m",  intraday_from),
        ]

    total_new, stop = 0, False
    for iv_api, iv_db, iv_from in intervals:
        if stop: break
        log.info("\n-- interval: %s --", iv_api)
        for bcode, exch, ticker in SYMBOLS:
            if _call_count >= args.max_calls:
                log.warning("max_calls=%d reached — stopping", args.max_calls)
                stop = True; break
            log.info("  %-16s [%s -> %s]", ticker, bcode, iv_api)
            try:
                n = download_one(api, store, bcode, exch, ticker,
                                 iv_api, iv_db, iv_from, today, args.max_calls)
                total_new += n
            except Exception as e:
                log.error("  ERROR %s: %s", ticker, e)

    log.info("=" * 70)
    log.info("DONE.  Total new: %d  Calls used: %d", total_new, _call_count)
    log.info("=" * 70)
    store.close()

if __name__ == "__main__":
    main()
