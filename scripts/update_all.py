#!/usr/bin/env python3
"""
scripts/update_all.py — Forward gap-fill EVERY symbol/interval already in the DB.

Brings the whole `candles` table current: for each (symbol, interval) pair that
already exists in the DB, fetches only the gap between its last stored candle and
now, and inserts. Idempotent (ON CONFLICT DO UPDATE) — safe to re-run.

Symbol → Breeze internal code resolution:
  • If the NSE ticker has a known Breeze internal code (from download_mapped.py),
    use it (e.g. RELIANCE → RELIND, BPCL → BHAPET).
  • Otherwise use the ticker directly (e.g. NIFTY, TCS, MARUTI, ITC) — these were
    originally downloaded with their ticker as the Breeze stock_code.

Also forward gap-fills `futures_candles` for its existing (symbol, expiry, interval).

Usage:
    python scripts/update_all.py                 # gap-fill everything to now
    python scripts/update_all.py --days 30       # cap look-back window (default 30)
    python scripts/update_all.py --no-futures    # skip futures_candles
    python scripts/update_all.py --intervals 1d,30m,5m   # only these intervals
    python scripts/update_all.py --symbols NIFTY,TCS     # only these symbols
    python scripts/update_all.py --dry-run       # list pairs + estimate API calls, no network

Safety: aborts after ABORT_AFTER_BAD_PAIRS consecutive (symbol,interval) pairs
that produced only errors (expired session / daily call cap), so a dead session
doesn't burn through thousands of failing calls.
"""
import os, sys, time, socket, logging, argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2, psycopg2.pool
from breeze_connect import BreezeConnect

from scripts.download_mapped import SYMBOLS as MAPPED_SYMBOLS  # (breeze_code, exch, db_sym, tier)

LOG_FILE = ROOT / "logs" / "update_all.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# DB interval label → Breeze API interval name
IV_API = {"1m": "1minute", "5m": "5minute", "30m": "30minute", "1d": "1day"}
# Breeze caps historical responses at ~1000 rows/call and returns only the
# NEWEST rows when capped. Keep each 1m chunk under that (2 days ≈ 750 bars).
CHUNK_DAYS = {"1minute": 2, "5minute": 10, "30minute": 25, "1day": 365}
# Intraday intervals are always re-swept over this many trailing days (even when
# their last candle looks "current") so that a capped prior fill or a collector
# that died mid-session gets its same-day hole refilled.  1d is skipped when current.
RESWEEP_DAYS = {"1m": 9, "5m": 5, "30m": 5}
# Symbols that Breeze's historical endpoint can no longer serve (dead / renamed /
# live-feed-only index).  Forward-filling them only burns calls.
SKIP_SYMBOLS = {"NIFTYJR", "ZOMATO", "NIFTYMIDSELECT"}
# Abort the run after this many consecutive pairs that yielded nothing but errors.
ABORT_AFTER_BAD_PAIRS = 8

# ticker → (breeze_code, exchange).  First mapping wins (map lists some twice).
CODE_MAP: Dict[str, Tuple[str, str]] = {}
for _bcode, _exch, _sym, _tier in MAPPED_SYMBOLS:
    CODE_MAP.setdefault(_sym, (_bcode, _exch))

# Indices the DB stores under a display name that is not the Breeze stock code.
# Without these the _code() fallback sends the DB name through as the stock code,
# Breeze rejects it, and the pair silently accumulates almost no rows.
CODE_MAP.setdefault("NIFTY_IT", ("CNXIT", "NSE"))

_last_call = 0.0
_call_count = 0
_err_count = 0          # fetch errors / non-200 responses in the current pair
CALLS_PER_MINUTE = 50
DRY_RUN = False

# Breeze sometimes accepts the connection and then never answers. The SDK sets no
# socket timeout, so such a call blocks the whole run indefinitely — a fill was
# once wedged ~10h on a single chunk. Bound every socket and retry a few times.
HTTP_TIMEOUT_SEC = 90
MAX_ATTEMPTS     = 3
socket.setdefaulttimeout(HTTP_TIMEOUT_SEC)


def _rate_limited(fn, *args, **kwargs):
    global _last_call, _call_count
    wait = (60.0 / CALLS_PER_MINUTE) - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    _call_count += 1
    return fn(*args, **kwargs)


def _fmt(dt): return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_dt(raw):
    if not raw:
        return None
    s = str(raw)[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _code(symbol: str) -> Tuple[str, str]:
    return CODE_MAP.get(symbol, (symbol, "NSE"))


class Store:
    def __init__(self, url):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=url)

    def coverage(self) -> List[Tuple[str, str, datetime]]:
        """Every (symbol, interval, last_ts) currently in candles."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT symbol, "interval", MAX(ts) '
                            'FROM candles GROUP BY symbol, "interval" ORDER BY symbol, "interval"')
                return [(s, i, t.replace(tzinfo=None) if t else None)
                        for s, i, t in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def futures_coverage(self) -> List[Tuple[str, object, str, datetime]]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT symbol, expiry, "interval", MAX(ts) '
                            'FROM futures_candles GROUP BY symbol, expiry, "interval" '
                            'ORDER BY symbol, expiry, "interval"')
                return [(s, e, i, t.replace(tzinfo=None) if t else None)
                        for s, e, i, t in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def insert(self, rows, table="candles"):
        if not rows:
            return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                if table == "candles":
                    cur.executemany(
                        'INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume) '
                        'VALUES (%(ts)s, %(symbol)s, %(interval)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s) '
                        'ON CONFLICT (symbol, "interval", ts) DO UPDATE SET '
                        'high=GREATEST(candles.high, EXCLUDED.high), low=LEAST(candles.low, EXCLUDED.low), '
                        'close=EXCLUDED.close, volume=EXCLUDED.volume', rows)
                else:
                    cur.executemany(
                        'INSERT INTO futures_candles (ts, symbol, expiry, "interval", open, high, low, close, volume) '
                        'VALUES (%(ts)s, %(symbol)s, %(expiry)s, %(interval)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s) '
                        'ON CONFLICT (symbol, expiry, "interval", ts) DO UPDATE SET '
                        'high=GREATEST(futures_candles.high, EXCLUDED.high), low=LEAST(futures_candles.low, EXCLUDED.low), '
                        'close=EXCLUDED.close, volume=EXCLUDED.volume', rows)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback(); raise
        finally:
            self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()


def _skip_weekend(dt: datetime) -> datetime:
    """Sat/Sun carry no bars - jump to Monday 00:00 so no chunk is wasted on them."""
    if dt.weekday() >= 5:
        dt = (dt + timedelta(days=7 - dt.weekday())).replace(hour=0, minute=0)
    return dt


def _chunk_span(iv_api: str, cursor: datetime, chunk_days: int) -> timedelta:
    """A 1m chunk that starts on a Friday spans the weekend to Monday: still only
    two trading days (~750 bars, under the 1000-row cap) but one call fewer per week."""
    if iv_api == "1minute" and cursor.weekday() == 4:
        return timedelta(days=4)
    return timedelta(days=chunk_days)


def estimate_calls(iv_api, from_dt, to_dt) -> int:
    chunk = CHUNK_DAYS.get(iv_api, 25)
    n, cursor = 0, from_dt
    if iv_api != "1day":
        cursor = _skip_weekend(cursor)
    while cursor < to_dt:
        n += 1
        cursor = min(cursor + _chunk_span(iv_api, cursor, chunk), to_dt) + timedelta(minutes=1)
        if iv_api != "1day":
            cursor = _skip_weekend(cursor)
    return n


def fetch_range(api, bcode, exch, iv_api, iv_db, db_sym, from_dt, to_dt,
                product_type="cash", expiry_date="", expiry_val=None) -> List[dict]:
    global _err_count
    _err_count = 0
    chunk = CHUNK_DAYS.get(iv_api, 25)
    rows, cursor = [], from_dt
    if iv_api != "1day":
        cursor = _skip_weekend(cursor)
    while cursor < to_dt:
        end = min(cursor + _chunk_span(iv_api, cursor, chunk), to_dt)
        resp = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = _rate_limited(
                    api.get_historical_data_v2,
                    interval=iv_api, from_date=_fmt(cursor), to_date=_fmt(end),
                    stock_code=bcode, exchange_code=exch, product_type=product_type,
                    expiry_date=expiry_date, right="", strike_price="")
                break
            except Exception as exc:
                log.warning("    fetch error %s[%s] %s-%s (attempt %d/%d): %s",
                            db_sym, iv_db, cursor.date(), end.date(),
                            attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(2 * attempt)
        if resp is None:
            # Chunk is unrecoverable — skip it and keep the run moving.
            _err_count += 1
            log.error("    giving up on %s[%s] %s-%s", db_sym, iv_db,
                      cursor.date(), end.date())
            cursor = end + timedelta(minutes=1)
            if iv_api != "1day":
                cursor = _skip_weekend(cursor)
            continue
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts:
                    continue
                try:
                    row = {"ts": ts, "symbol": db_sym, "interval": iv_db,
                           "open": float(raw["open"]), "high": float(raw["high"]),
                           "low": float(raw["low"]), "close": float(raw["close"]),
                           "volume": int(float(raw.get("volume", 0) or 0))}
                    if expiry_val is not None:
                        row["expiry"] = expiry_val
                    rows.append(row)
                except (KeyError, TypeError, ValueError):
                    pass
        else:
            _err_count += 1
            log.warning("    non-200 %s[%s]: %s", db_sym, iv_db, resp.get("Error"))
        # Advance by 1 minute (not 1 day) so intraday chunk boundaries stay
        # contiguous — a day-step drops ~1 trading day at every boundary.
        cursor = end + timedelta(minutes=1)
        if iv_api != "1day":
            cursor = _skip_weekend(cursor)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Max look-back window (default 30)")
    ap.add_argument("--no-futures", action="store_true", help="Skip futures_candles")
    ap.add_argument("--intervals", default="", help="Comma list of DB intervals to fill (default all)")
    ap.add_argument("--symbols", default="", help="Comma list of symbols to fill (default all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched and the estimated API calls; no network")
    args = ap.parse_args()
    global DRY_RUN
    DRY_RUN = args.dry_run
    only_ivs = {x.strip() for x in args.intervals.split(",") if x.strip()}
    only_syms = {x.strip().upper() for x in args.symbols.split(",") if x.strip()}

    store = Store(os.environ["DB_URL"])
    api = None
    if not DRY_RUN:
        api = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
        api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                             session_token=os.environ["BREEZE_SESSION_TOKEN"])
        log.info("Breeze session OK")

    now = datetime.now().replace(second=0, microsecond=0)
    window_start = now - timedelta(days=args.days)
    # A pair is "current" if its last candle is within this cutoff of now.
    up_to_date_cutoff = now - timedelta(hours=20)

    # ── Spot / index / equity candles ─────────────────────────────────────────
    cov = store.coverage()
    log.info("=" * 70)
    log.info("SPOT/EQUITY UPDATE — %d (symbol,interval) pairs across %d symbols",
             len(cov), len({s for s, _, _ in cov}))
    log.info("=" * 70)

    total_new = updated = skipped = est_calls = bad_pairs = 0
    for symbol, iv_db, last_ts in cov:
        iv_api = IV_API.get(iv_db)
        if iv_api is None or symbol in SKIP_SYMBOLS:
            continue
        if only_ivs and iv_db not in only_ivs:
            continue
        if only_syms and symbol not in only_syms:
            continue
        # Intraday intervals are always re-swept over a bounded trailing window
        # (RESWEEP_DAYS) so a capped prior fill or a collector that died
        # mid-session gets refilled; 1d is skipped when current.
        resweep = RESWEEP_DAYS.get(iv_db)
        if resweep is None and last_ts and last_ts >= up_to_date_cutoff:
            skipped += 1
            continue
        bcode, exch = _code(symbol)
        fetch_from = max((last_ts + timedelta(minutes=1)) if last_ts else window_start,
                         window_start)
        if resweep:
            fetch_from = max(min(fetch_from, now - timedelta(days=resweep)), window_start)
        if fetch_from >= now:
            skipped += 1
            continue
        if DRY_RUN:
            c = estimate_calls(iv_api, fetch_from, now)
            est_calls += c
            log.info("  %-14s [%-3s]  %s -> now  ~%d calls", symbol, iv_db, fetch_from.date(), c)
            continue
        rows = fetch_range(api, bcode, exch, iv_api, iv_db, symbol, fetch_from, now)
        n = store.insert(rows, "candles")
        if n:
            total_new += n
            updated += 1
            bad_pairs = 0
            log.info("  %-14s [%-3s]  %s -> now  +%d  (via %s, calls=%d)",
                     symbol, iv_db, fetch_from.date(), n, bcode, _call_count)
        elif _err_count:
            bad_pairs += 1
            if bad_pairs >= ABORT_AFTER_BAD_PAIRS:
                log.error("ABORT: %d consecutive pairs returned only errors "
                          "(session expired or daily call cap?). calls=%d",
                          bad_pairs, _call_count)
                store.close()
                sys.exit(2)

    if DRY_RUN:
        log.info("DRY RUN: spot pairs to fetch=%d  skipped(current)=%d  estimated calls=%d "
                 "(~%d min at %d/min)", len(cov) - skipped, skipped, est_calls,
                 est_calls // CALLS_PER_MINUTE, CALLS_PER_MINUTE)
    else:
        log.info("Spot done. updated pairs=%d  skipped(current)=%d  new candles=%d  calls=%d",
                 updated, skipped, total_new, _call_count)

    # ── Futures candles ───────────────────────────────────────────────────────
    if not args.no_futures:
        fcov = store.futures_coverage()
        log.info("=" * 70)
        log.info("FUTURES UPDATE — %d (symbol,expiry,interval) pairs", len(fcov))
        log.info("=" * 70)
        f_new = f_updated = f_skipped = f_est = 0
        for symbol, expiry, iv_db, last_ts in fcov:
            iv_api = IV_API.get(iv_db)
            if iv_api is None:
                continue
            if only_ivs and iv_db not in only_ivs:
                continue
            if only_syms and symbol not in only_syms:
                continue
            # A contract is complete once we hold its expiry-day candles; never
            # fetch past expiry (Breeze returns nothing / errors for that range).
            contract_end = datetime.combine(expiry, datetime.max.time()).replace(microsecond=0)
            fetch_to = min(now, contract_end)
            if last_ts and last_ts.date() >= expiry:
                f_skipped += 1
                continue
            resweep = RESWEEP_DAYS.get(iv_db)
            if resweep is None and last_ts and last_ts >= up_to_date_cutoff:
                f_skipped += 1
                continue
            bcode, _exch = _code(symbol)
            fetch_from = max((last_ts + timedelta(minutes=1)) if last_ts else window_start,
                             window_start)
            if resweep:
                fetch_from = max(min(fetch_from, fetch_to - timedelta(days=resweep)), window_start)
            if fetch_from >= fetch_to:
                f_skipped += 1
                continue
            if DRY_RUN:
                c = estimate_calls(iv_api, fetch_from, fetch_to)
                f_est += c
                log.info("  %-10s %s [%-3s]  %s -> %s  ~%d calls",
                         symbol, expiry, iv_db, fetch_from.date(), fetch_to.date(), c)
                continue
            expiry_api = expiry.strftime("%Y-%m-%dT06:00:00.000Z")
            rows = fetch_range(api, bcode, "NFO", iv_api, iv_db, symbol, fetch_from, fetch_to,
                               product_type="futures", expiry_date=expiry_api,
                               expiry_val=expiry)
            n = store.insert(rows, "futures_candles")
            if n:
                f_new += n
                f_updated += 1
                log.info("  %-10s %s [%-3s]  +%d  (calls=%d)",
                         symbol, expiry, iv_db, n, _call_count)
        if DRY_RUN:
            log.info("DRY RUN: futures estimated calls=%d  skipped=%d", f_est, f_skipped)
        else:
            log.info("Futures done. updated=%d  skipped(current)=%d  new=%d  calls=%d",
                     f_updated, f_skipped, f_new, _call_count)

    log.info("=" * 70)
    log.info("ALL DONE.  total spot new=%d  total API calls=%d", total_new, _call_count)
    log.info("=" * 70)
    store.close()


if __name__ == "__main__":
    main()
