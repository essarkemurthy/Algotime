#!/usr/bin/env python3
"""
scripts/download_mapped.py — Download history for symbols whose Breeze stock_code
differs from the NSE ticker used in the DB.

Many symbols that returned 0 rows in bulk_download.py (which uses NSE tickers
directly as stock_codes) actually require Breeze-specific internal codes.
This script maps NSE_TICKER → BREEZE_CODE and downloads into the DB under
the NSE ticker.

Found via exhaustive symbols.json lookup + live API verification.
LTIM (LTIMindtree) is absent from Breeze's master — no data available.
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

LOG_FILE = ROOT / "logs" / "download_mapped.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Symbol mapping: (breeze_code, exchange, db_symbol, tier) ─────────────────
# tier: "index" | "nifty50" | "next50" | "additional"
SYMBOLS = [
    # ── Missing indices (all 4 intervals) ─────────────────────────────────────
    ("BSESEN", "BSE", "SENSEX",    "index"),
    ("NIFFIN", "NSE", "FINNIFTY",  "index"),
    ("NIFMID", "NSE", "MIDCPNIFTY","index"),

    # ── Missing Nifty50 (5m, 30m, 1d) ────────────────────────────────────────
    ("SBILIF", "NSE", "SBILIFE",   "nifty50"),
    ("ZOMLIM", "NSE", "ETERNAL",   "nifty50"),

    # ── Bank Nifty missing constituents (5m, 30m, 1d) ────────────────────────
    ("AUSMA",  "NSE", "AUBANK",    "nifty50"),
    ("PUNBAN", "NSE", "PNB",       "nifty50"),
    ("BANBAN", "NSE", "BANDHANBNK","nifty50"),

    # ── Nifty50 backfill (short history) ─────────────────────────────────────
    ("TATMOT", "NSE", "TATAMOTORS","nifty50"),

    # ── Missing Next50 (30m, 1d) ──────────────────────────────────────────────
    ("AURPHA", "NSE", "AUROPHARMA","next50"),
    ("HINAER", "NSE", "HAL",       "next50"),
    ("BHAINF", "NSE", "INDUSTOWER","next50"),
    ("ORAFIN", "NSE", "OFSS",      "next50"),
    ("PAGIND", "NSE", "PAGEIND",   "next50"),
    ("TATGLO", "NSE", "TATACONSUM","next50"),
    ("TATCHE", "NSE", "TATACHEM",  "next50"),
    ("MACDEV", "NSE", "LODHA",     "next50"),
    ("TORPOW", "NSE", "TORNTPOWER","next50"),
    ("ADATRA", "NSE", "ADANITRANS","next50"),

    # ── Missing Additional (1d only) ─────────────────────────────────────────
    ("MAXHEA", "NSE", "MAXHEALTH", "additional"),
    ("ALKLAB", "NSE", "ALKEM",     "additional"),
    ("ADIFAS", "NSE", "ABFRL",     "additional"),
    ("ADICAP", "NSE", "ABCAPITAL", "additional"),
    ("BALIND", "NSE", "BALKRISIND","additional"),
    ("BATIND", "NSE", "BATAINDIA", "additional"),
    ("EXIIND", "NSE", "EXIDEIND",  "additional"),
    ("INDIBA", "NSE", "INDIANB",   "additional"),
    ("JUBFOO", "NSE", "JUBLFOOD",  "additional"),
    ("KANNER", "NSE", "KANSAINER", "additional"),
    ("DRLAL",  "NSE", "LALPATHLAB","additional"),
    ("LIC",    "NSE", "LICI",      "additional"),
    ("MAXFIN", "NSE", "MFSL",      "additional"),
    ("MRFTYR", "NSE", "MRF",       "additional"),
    ("NATALU", "NSE", "NATIONALUM","additional"),
    ("POWFIN", "NSE", "PFC",       "additional"),
    ("PBFINT", "NSE", "POLICYBZR", "additional"),
    ("SYNINT", "NSE", "SYNGENE",   "additional"),
    ("YESBAN", "NSE", "YESBANK",   "additional"),
    ("FSNECO", "NSE", "NYKAA",     "additional"),
    ("DEENIT", "NSE", "DEEPAKNTR", "additional"),
    ("KAJCER", "NSE", "KAJARIACER","additional"),
]

# Intervals per tier
TIER_INTERVALS = {
    "index":      ["1minute", "5minute", "30minute", "1day"],
    "nifty50":    ["5minute", "30minute", "1day"],
    "next50":     ["30minute", "1day"],
    "additional": ["1day"],
}
INTERVAL_DB = {"1minute":"1m","5minute":"5m","30minute":"30m","1day":"1d"}
CHUNK_DAYS  = {"1minute":25,"5minute":25,"30minute":25,"1day":365}

# ── Rate limiter ──────────────────────────────────────────────────────────────
_last_call = 0.0
_call_count = 0
CALLS_PER_MINUTE = 50

def _rate_limited(fn, *args, **kwargs):
    global _last_call, _call_count
    gap  = 60.0 / CALLS_PER_MINUTE
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

# ── DB store ──────────────────────────────────────────────────────────────────
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
                ts  = row[0] if row and row[0] else None
                return ts.replace(tzinfo=None) if ts else None
        finally: self._pool.putconn(conn)

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
        finally: self._pool.putconn(conn)

    def close(self): self._pool.closeall()


# ── Downloader ────────────────────────────────────────────────────────────────
def fetch_range(api, bcode, exch, iv_api, iv_db, db_sym, from_dt, to_dt) -> List[dict]:
    chunk = CHUNK_DAYS.get(iv_api, 25)
    rows, cursor = [], from_dt
    while cursor < to_dt:
        end  = min(cursor + timedelta(days=chunk), to_dt)
        resp = _rate_limited(
            api.get_historical_data_v2,
            interval=iv_api, from_date=_fmt(cursor), to_date=_fmt(end),
            stock_code=bcode, exchange_code=exch, product_type="cash",
            expiry_date="", right="", strike_price="")
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts: continue
                try:
                    rows.append({"ts":ts,"symbol":db_sym,"interval":iv_db,
                        "open":float(raw["open"]), "high":float(raw["high"]),
                        "low":float(raw["low"]),   "close":float(raw["close"]),
                        "volume":int(float(raw.get("volume",0) or 0))})
                except (KeyError,TypeError,ValueError): pass
        cursor = end + timedelta(days=1)
    return rows


def download_one(api, store, bcode, exch, db_sym, iv_api, iv_db, from_dt, to_dt) -> int:
    new = 0
    first = store.first_ts(db_sym, iv_db)
    if first and first > from_dt + timedelta(days=1):
        rows = fetch_range(api, bcode, exch, iv_api, iv_db, db_sym,
                           from_dt, first - timedelta(days=1))
        if rows:
            store.insert(rows); new += len(rows)
            log.info("    bwd +%d  calls=%d", len(rows), _call_count)
    last = store.last_ts(db_sym, iv_db)
    fetch_from = (last + timedelta(minutes=1)) if last else from_dt
    fetch_from = max(fetch_from, from_dt)
    if fetch_from < to_dt - timedelta(hours=1):
        rows = fetch_range(api, bcode, exch, iv_api, iv_db, db_sym, fetch_from, to_dt)
        if rows:
            store.insert(rows); new += len(rows)
            log.info("    fwd +%d  calls=%d", len(rows), _call_count)
        elif not last:
            log.warning("    0 candles returned for %s[%s] — Breeze may not have this data", db_sym, iv_db)
    else:
        log.info("    up to date")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days",   type=int, default=365, help="History depth (default: 365)")
    ap.add_argument("--idays",  type=int, default=365, help="Intraday depth (default: 365)")
    ap.add_argument("--tiers",  nargs="+",
                    choices=["index","nifty50","next50","additional"],
                    default=["index","nifty50","next50","additional"])
    ap.add_argument("--symbols", nargs="+", metavar="SYM",
                    help="Download only these NSE tickers (default: all mapped)")
    args = ap.parse_args()

    log.info("=" * 70)
    log.info("MAPPED SYMBOL DOWNLOAD  (Breeze-code -> NSE-ticker)")
    log.info("=" * 70)

    store = Store(os.environ["DB_URL"])
    api   = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                         session_token=os.environ["BREEZE_SESSION_TOKEN"])
    log.info("Breeze session OK")

    today       = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    far_ago     = today - timedelta(days=args.days)
    intra_from  = today - timedelta(days=args.idays)

    # Filter symbols
    syms = [(b,e,d,t) for b,e,d,t in SYMBOLS
            if t in args.tiers
            and (not args.symbols or d.upper() in [s.upper() for s in args.symbols])]
    log.info("Symbols: %d  |  Tiers: %s", len(syms), args.tiers)

    total_new = 0
    for bcode, exch, db_sym, tier in syms:
        intervals = TIER_INTERVALS[tier]
        log.info("%-15s  [%s -> %s]  intervals: %s",
                 db_sym, bcode, tier, " ".join(intervals))
        for iv_api in intervals:
            iv_db  = INTERVAL_DB[iv_api]
            iv_from = intra_from if iv_api != "1day" else far_ago
            try:
                n = download_one(api, store, bcode, exch, db_sym,
                                 iv_api, iv_db, iv_from, today)
                total_new += n
            except Exception as exc:
                log.error("  ERROR %s[%s]: %s", db_sym, iv_db, exc)

    log.info("=" * 70)
    log.info("DONE.  Total new candles: %d  API calls used: %d", total_new, _call_count)
    log.info("=" * 70)
    store.close()


if __name__ == "__main__":
    main()
