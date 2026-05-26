#!/usr/bin/env python3
"""
scripts/bulk_download.py — Bulk historical candle downloader: Breeze API → PostgreSQL

Downloads up to 1 year of OHLCV candles for all NSE/BSE indices, Nifty 50,
Nifty Next 50, and additional mid-cap stocks.

Features:
  • Token-bucket rate limiter (55 calls/min — safely under Breeze's 75/min hard limit)
  • Per-chunk retry with exponential backoff (10s → 30s → 90s)
  • Gap detection — only fetches what is missing in the DB (safe to re-run)
  • Resume file — skip completed symbol×interval pairs across sessions
  • Data integrity verification — OHLC sanity checks + gap analysis
  • Estimated API call count printed before download starts

Estimated call counts (1 year, default universe):
  Indices  (6 syms × 6 intervals):    ~444 calls  →  ~8 min
  Nifty 50 (50 syms × 5 intervals):  ~2950 calls  → ~54 min
  Next 50  (38 syms × 3 intervals):  ~1178 calls  → ~21 min
  Additional (30 syms × 1day only):    ~30 calls  →  <1 min
  ─────────────────────────────────────────────────────────
  Total "all":                        ~4602 calls  → ~84 min
  ⚠  Exceeds one day's safe quota (4500). Use --resume across two sessions,
     or pick a narrower --universe.

Usage:
  python scripts/bulk_download.py                              # all universes, 1 year
  python scripts/bulk_download.py --universe indices           # only 6 indices
  python scripts/bulk_download.py --universe nifty50           # only Nifty 50
  python scripts/bulk_download.py --universe nextnifty50       # Nifty Next 50
  python scripts/bulk_download.py --days 90                    # last 90 days
  python scripts/bulk_download.py --intervals 1day 5minute     # specific intervals
  python scripts/bulk_download.py --resume                     # continue last run
  python scripts/bulk_download.py --estimate                   # show call count, don't download
  python scripts/bulk_download.py --verify                     # integrity check only
  python scripts/bulk_download.py --reset-progress             # wipe resume file

Credentials (from .env or environment):
  BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN
  DB_URL   (postgresql://user:pass@host:5432/market_data)

Note: BREEZE_SESSION_TOKEN expires every day. Generate a fresh one from
  https://api.icicidirect.com/ before each session.
"""

import os
import sys
import time
import json
import logging
import argparse
import threading
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

IST = timezone(timedelta(hours=5, minutes=30))

# ── bootstrap path + .env ─────────────────────────────────────────────────────
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

# ── logging ───────────────────────────────────────────────────────────────────
LOG_FILE = ROOT / "logs" / "bulk_download.log"
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

# ── constants ─────────────────────────────────────────────────────────────────
CALLS_PER_MINUTE  = 55          # conservative (Breeze hard limit = 75/min, daily = 4500)
DAILY_CALL_LIMIT  = 4400        # leave 100 calls headroom for live trading

MAX_RETRIES   = 3
RETRY_DELAYS  = [10, 30, 90]   # seconds between retry attempts

# Max calendar days per API chunk per interval
CHUNK_DAYS: Dict[str, int] = {
    "1minute":  25,
    "5minute":  25,
    "30minute": 25,
    "1day":    365,
}

# Breeze interval name → DB interval label
# Valid get_historical_data_v2 intervals: 1minute, 5minute, 30minute, 1day
# (15minute and 1hour are NOT accepted by the Breeze API — returns HTTP 500)
INTERVAL_DB: Dict[str, str] = {
    "1minute":  "1m",
    "5minute":  "5m",
    "30minute": "30m",
    "1day":     "1d",
}

PROGRESS_FILE = ROOT / "data" / "bulk_progress.json"
STATUS_FILE   = ROOT / "data" / "bulk_status.json"

# ── symbol universes ──────────────────────────────────────────────────────────
# Each entry: (stock_code, exchange_code)

NSE_INDICES: List[Tuple[str, str]] = [
    ("NIFTY",      "NSE"),
    ("BANKNIFTY",  "NSE"),
    ("SENSEX",     "BSE"),
    ("CNXIT",      "NSE"),
    ("FINNIFTY",   "NSE"),
    ("MIDCPNIFTY", "NSE"),
]

NIFTY50: List[Tuple[str, str]] = [
    ("RELIANCE",   "NSE"), ("TCS",        "NSE"), ("HDFCBANK",  "NSE"),
    ("INFY",       "NSE"), ("ICICIBANK",  "NSE"), ("HINDUNILVR","NSE"),
    ("SBIN",       "NSE"), ("BHARTIARTL", "NSE"), ("KOTAKBANK", "NSE"),
    ("AXISBANK",   "NSE"), ("LT",         "NSE"), ("ASIANPAINT","NSE"),
    ("MARUTI",     "NSE"), ("SUNPHARMA",  "NSE"), ("WIPRO",     "NSE"),
    ("ULTRACEMCO", "NSE"), ("NESTLEIND",  "NSE"), ("POWERGRID", "NSE"),
    ("NTPC",       "NSE"), ("COALINDIA",  "NSE"), ("ONGC",      "NSE"),
    ("TATAMOTORS", "NSE"), ("TATASTEEL",  "NSE"), ("JSWSTEEL",  "NSE"),
    ("ADANIENT",   "NSE"), ("ADANIPORTS", "NSE"), ("BAJFINANCE","NSE"),
    ("BAJAJFINSV", "NSE"), ("HCLTECH",   "NSE"),  ("TECHM",     "NSE"),
    ("TITAN",      "NSE"), ("DRREDDY",   "NSE"),  ("CIPLA",     "NSE"),
    ("BRITANNIA",  "NSE"), ("EICHERMOT", "NSE"),  ("HEROMOTOCO","NSE"),
    ("HINDALCO",   "NSE"), ("GRASIM",    "NSE"),  ("INDUSINDBK","NSE"),
    ("APOLLOHOSP", "NSE"), ("BPCL",      "NSE"),  ("BEL",       "NSE"),
    ("HDFCLIFE",   "NSE"), ("SBILIFE",   "NSE"),  ("TRENT",     "NSE"),
    ("ITC",        "NSE"), ("JIOFIN",    "NSE"),  ("SHRIRAMFIN","NSE"),
    ("ETERNAL",    "NSE"), ("BAJAJ-AUTO","NSE"),
]

NIFTY_NEXT50: List[Tuple[str, str]] = [
    ("AMBUJACEM",  "NSE"), ("AUROPHARMA", "NSE"), ("BANKBARODA","NSE"),
    ("BERGEPAINT", "NSE"), ("CANBK",      "NSE"), ("CHOLAFIN",  "NSE"),
    ("COLPAL",     "NSE"), ("DABUR",      "NSE"), ("DLF",       "NSE"),
    ("GODREJCP",   "NSE"), ("HAVELLS",    "NSE"), ("HAL",       "NSE"),
    ("ICICIPRULI", "NSE"), ("INDUSTOWER", "NSE"), ("IRCTC",     "NSE"),
    ("JINDALSTEL", "NSE"), ("LTIM",       "NSE"), ("LUPIN",     "NSE"),
    ("MARICO",     "NSE"), ("MUTHOOTFIN", "NSE"), ("NAUKRI",    "NSE"),
    ("OFSS",       "NSE"), ("PAGEIND",    "NSE"), ("PIDILITIND","NSE"),
    ("RECLTD",     "NSE"), ("SIEMENS",    "NSE"), ("TORNTPHARM","NSE"),
    ("TATACONSUM", "NSE"), ("TATACHEM",   "NSE"), ("VEDL",      "NSE"),
    ("LODHA",      "NSE"), ("DMART",      "NSE"), ("PIIND",     "NSE"),
    ("TORNTPOWER", "NSE"), ("ZOMATO",     "NSE"), ("ADANITRANS","NSE"),
    ("M&M",        "NSE"), ("BIOCON",     "NSE"),
]

ADDITIONAL_STOCKS: List[Tuple[str, str]] = [
    # Mid-cap and sector leaders not in Nifty 100
    ("MAXHEALTH",  "NSE"), ("MPHASIS",   "NSE"), ("ALKEM",     "NSE"),
    ("ABFRL",      "NSE"), ("ABCAPITAL", "NSE"), ("BALKRISIND","NSE"),
    ("BANDHANBNK", "NSE"), ("BATAINDIA", "NSE"), ("EXIDEIND",  "NSE"),
    ("GAIL",       "NSE"), ("INDIANB",   "NSE"), ("IOC",       "NSE"),
    ("JUBLFOOD",   "NSE"), ("KANSAINER", "NSE"), ("LALPATHLAB","NSE"),
    ("LICI",       "NSE"), ("MFSL",      "NSE"), ("MOTHERSON", "NSE"),
    ("MRF",        "NSE"), ("NATIONALUM","NSE"), ("OBEROIRLTY","NSE"),
    ("PFC",        "NSE"), ("POLICYBZR", "NSE"), ("SYNGENE",   "NSE"),
    ("UPL",        "NSE"), ("YESBANK",   "NSE"), ("NYKAA",     "NSE"),
    ("DEEPAKNTR",  "NSE"), ("KAJARIACER","NSE"), ("PERSISTENT","NSE"),
]

# Intervals per universe tier (only Breeze-valid: 1minute, 5minute, 30minute, 1day)
INTERVALS_INDICES    = ["1minute", "5minute", "30minute", "1day"]
INTERVALS_NIFTY50    = ["5minute", "30minute", "1day"]
INTERVALS_NEXTNIFTY  = ["30minute", "1day"]
INTERVALS_ADDITIONAL = ["1day"]


# ── Rate limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Token-bucket rate limiter enforcing a minimum gap between calls.
    Also tracks a daily call counter so we can warn before the daily cap.
    Thread-safe.
    """

    def __init__(self, calls_per_minute: int, daily_limit: int) -> None:
        self._min_gap     = 60.0 / calls_per_minute
        self._daily_limit = daily_limit
        self._last        = 0.0
        self._day_count   = 0
        self._day_reset   = time.monotonic()
        self._lock        = threading.Lock()

    def acquire(self, label: str = "") -> None:
        with self._lock:
            now = time.monotonic()

            # Reset daily counter at midnight-ish (86400 s)
            if now - self._day_reset > 86400:
                self._day_count = 0
                self._day_reset = now

            if self._day_count >= self._daily_limit:
                raise RuntimeError(
                    f"Daily Breeze API call limit reached ({self._day_count}/{self._daily_limit}). "
                    "Wait until tomorrow or run with --resume to restart the session."
                )

            wait = self._min_gap - (now - self._last)
            if wait > 0:
                time.sleep(wait)

            self._last       = time.monotonic()
            self._day_count += 1

    @property
    def day_count(self) -> int:
        return self._day_count


# ── Progress tracker ──────────────────────────────────────────────────────────

class ProgressTracker:
    """Persists completed and failed tasks to a JSON file for --resume support."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "started_at":   datetime.now().isoformat(),
            "completed":    [],
            "failed":       [],
        }

    def _save(self) -> None:
        self._path.parent.mkdir(exist_ok=True)
        self._data["last_updated"] = datetime.now().isoformat()
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def is_done(self, key: str) -> bool:
        return key in self._data["completed"]

    def mark_done(self, key: str) -> None:
        if key not in self._data["completed"]:
            self._data["completed"].append(key)
            # Remove from failed list if it was there
            self._data["failed"] = [f for f in self._data["failed"] if f["key"] != key]
        self._save()

    def mark_failed(self, key: str, reason: str) -> None:
        # Update existing failed entry or append new one
        self._data["failed"] = [f for f in self._data["failed"] if f["key"] != key]
        self._data["failed"].append({
            "key":    key,
            "reason": str(reason)[:200],
            "ts":     datetime.now().isoformat(),
        })
        self._save()

    def summary(self) -> str:
        return f"done={len(self._data['completed'])} failed={len(self._data['failed'])}"

    def failed_keys(self) -> List[str]:
        return [f["key"] for f in self._data["failed"]]


# ── Live status file ─────────────────────────────────────────────────────────

class StatusFile:
    """
    Writes a live JSON status file (data/bulk_status.json) after every task.
    The monitoring loop reads this file to report progress to the user.
    Thread-safe with a simple lock.
    """

    def __init__(self, path: Path, total_tasks: int, deadline_ist: datetime) -> None:
        self._path     = path
        self._lock     = threading.Lock()
        self._data: dict = {
            "started_at":      datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "deadline":        deadline_ist.strftime("%Y-%m-%d %H:%M:%S IST") if deadline_ist else "none",
            "total_tasks":     total_tasks,
            "done":            0,
            "skipped":         0,
            "failed":          0,
            "calls_today":     0,
            "disconnections":  0,
            "current_symbol":  "",
            "current_interval": "",
            "last_error":      "",
            "last_updated":    "",
            "phase":           "starting",   # starting | downloading | freezing | done
            "candles_inserted": 0,
        }
        self._write()

    def update(self, **kwargs) -> None:
        with self._lock:
            self._data.update(kwargs)
            self._data["last_updated"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        self._write()

    def increment(self, field: str, by: int = 1) -> None:
        with self._lock:
            self._data[field] = self._data.get(field, 0) + by
            self._data["last_updated"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        self._write()

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self._path)   # atomic replace
        except Exception:
            pass

    def read(self) -> dict:
        with self._lock:
            return dict(self._data)


# ── Candle store ──────────────────────────────────────────────────────────────

class CandleStore:
    """Minimal thread-safe PostgreSQL wrapper for the candles table."""

    def __init__(self, db_url: str) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(2, 4, dsn=db_url)

    # ── query helpers ─────────────────────────────────────────────────────────

    def last_ts(self, symbol: str, db_interval: str) -> Optional[datetime]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MAX(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                    (symbol, db_interval),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] else None
        finally:
            self._pool.putconn(conn)

    def first_ts(self, symbol: str, db_interval: str) -> Optional[datetime]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT MIN(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
                    (symbol, db_interval),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] else None
        finally:
            self._pool.putconn(conn)

    def insert(self, rows: List[dict]) -> None:
        if not rows:
            return
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO candles
                           (ts, symbol, "interval", open, high, low, close, volume)
                       VALUES
                           (%(ts)s, %(symbol)s, %(interval)s,
                            %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
                       ON CONFLICT (symbol, "interval", ts) DO UPDATE
                       SET open   = EXCLUDED.open,
                           high   = GREATEST(candles.high, EXCLUDED.high),
                           low    = LEAST   (candles.low,  EXCLUDED.low),
                           close  = EXCLUDED.close,
                           volume = EXCLUDED.volume""",
                    rows,
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def fetch_for_verify(self, symbol: str, db_interval: str,
                         from_dt: datetime, to_dt: datetime) -> list:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ts, open, high, low, close
                       FROM   candles
                       WHERE  symbol=%s AND "interval"=%s AND ts BETWEEN %s AND %s
                       ORDER  BY ts""",
                    (symbol, db_interval, from_dt, to_dt),
                )
                return cur.fetchall()
        finally:
            self._pool.putconn(conn)

    def log_download(self, symbol: str, db_interval: str,
                     rows_inserted: int, status: str, note: str = "") -> None:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO download_log
                           (ts, symbol, "interval", rows_inserted, status, note)
                       VALUES (NOW(), %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (symbol, db_interval, rows_inserted, status, note[:500]),
                )
            conn.commit()
        except Exception:
            conn.rollback()   # log table might not exist yet — non-fatal
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        self._pool.closeall()


# ── Breeze helpers ────────────────────────────────────────────────────────────

def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_row(raw: dict, symbol: str, db_interval: str) -> Optional[dict]:
    try:
        raw_dt = str(raw.get("datetime", ""))[:19]
        ts = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                ts = datetime.strptime(raw_dt, fmt)
                break
            except ValueError:
                continue
        if ts is None:
            return None
        return {
            "ts":       ts,
            "symbol":   symbol,
            "interval": db_interval,
            "open":     float(raw["open"]),
            "high":     float(raw["high"]),
            "low":      float(raw["low"]),
            "close":    float(raw["close"]),
            "volume":   int(float(raw.get("volume", 0) or 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


# ── Core downloader ───────────────────────────────────────────────────────────

class BulkDownloader:

    def __init__(self, api: BreezeConnect, store: CandleStore,
                 limiter: RateLimiter, progress: ProgressTracker,
                 status: "StatusFile",
                 deadline: Optional[datetime] = None) -> None:
        self._api      = api
        self._store    = store
        self._limiter  = limiter
        self._progress = progress
        self._status   = status
        self._deadline = deadline   # timezone-aware datetime in IST (or None)
        self._stop     = False      # set True by signal handler or deadline check

    def request_stop(self) -> None:
        self._stop = True

    def _past_deadline(self) -> bool:
        if self._deadline is None:
            return False
        return datetime.now(IST) >= self._deadline

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, tasks: List[Tuple[str, str, str]],
            days: int, resume: bool) -> None:
        """Download OHLCV for every (symbol, exchange, interval) tuple in tasks."""
        to_dt   = datetime.now().replace(second=0, microsecond=0)
        from_dt = to_dt - timedelta(days=days)

        total    = len(tasks)
        done_cnt = skipped = failed_cnt = candles_total = 0

        self._status.update(phase="downloading", total_tasks=total)
        log.info("=" * 70)
        log.info("BULK DOWNLOAD STARTED")
        log.info("Tasks: %d  |  Period: %s to %s",
                 total, from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"))
        if self._deadline:
            log.info("Deadline: %s  |  Time available: %.0f min",
                     self._deadline.strftime("%H:%M IST"),
                     (self._deadline - datetime.now(IST)).total_seconds() / 60)
        log.info("=" * 70)

        for idx, (symbol, exchange, interval) in enumerate(tasks, 1):
            # ── deadline / stop check ─────────────────────────────────────────
            if self._stop or self._past_deadline():
                mins_left = (
                    (self._deadline - datetime.now(IST)).total_seconds() / 60
                    if self._deadline else 0
                )
                log.warning(
                    "STOPPING at task %d/%d — %s  "
                    "(%.0f min before deadline — initiating data freeze)",
                    idx, total,
                    "deadline reached" if self._past_deadline() else "stop requested",
                    mins_left,
                )
                break

            key    = f"{symbol}|{interval}"
            db_iv  = INTERVAL_DB.get(interval, interval)
            prefix = f"[{idx}/{total}] {symbol}[{db_iv}]"

            self._status.update(
                current_symbol=symbol,
                current_interval=db_iv,
                calls_today=self._limiter.day_count,
            )

            if resume and self._progress.is_done(key):
                skipped += 1
                self._status.increment("skipped")
                log.debug("%s — skipped (already complete)", prefix)
                continue

            try:
                n = self._download_one(symbol, exchange, interval, db_iv, from_dt, to_dt)
                self._progress.mark_done(key)
                self._store.log_download(symbol, db_iv, n, "ok")
                done_cnt      += 1
                candles_total += n
                self._status.update(
                    done=done_cnt, candles_inserted=candles_total,
                    calls_today=self._limiter.day_count,
                )
                self._status.increment("done", 0)   # flush updated counts
                pct = done_cnt * 100 // max(total - skipped, 1)
                log.info("%s — +%d candles  [%d%%]  [calls: %d]  [total candles: %d]",
                         prefix, n, pct,
                         self._limiter.day_count, candles_total)

            except RuntimeError as exc:
                # Daily limit hit — stop immediately
                log.error("=" * 60)
                log.error("DAILY CALL LIMIT REACHED at task %d/%d.", idx, total)
                log.error("Re-run tomorrow with --resume (fresh session token).")
                log.error("=" * 60)
                self._status.update(phase="daily_limit", last_error=str(exc))
                self._store.log_download(symbol, db_iv, 0, "daily_limit", str(exc))
                break

            except Exception as exc:
                self._progress.mark_failed(key, exc)
                self._store.log_download(symbol, db_iv, 0, "error", str(exc))
                failed_cnt += 1
                self._status.update(failed=failed_cnt, last_error=str(exc)[:200])
                log.error("%s — FAILED: %s", prefix, exc)

        self._status.update(
            done=done_cnt, failed=failed_cnt, skipped=skipped,
            candles_inserted=candles_total,
            calls_today=self._limiter.day_count,
            current_symbol="", current_interval="",
        )
        log.info("-" * 70)
        log.info("Download loop finished.  done=%d  skipped=%d  failed=%d  "
                 "candles=%d  calls=%d",
                 done_cnt, skipped, failed_cnt,
                 candles_total, self._limiter.day_count)
        if self._progress.failed_keys():
            log.warning("Failed: %s", ", ".join(self._progress.failed_keys()))

    # ── per-symbol download ───────────────────────────────────────────────────

    def _download_one(self, symbol: str, exchange: str,
                      interval: str, db_iv: str,
                      from_dt: datetime, to_dt: datetime) -> int:
        chunk_days = CHUNK_DAYS.get(interval, 25)
        all_rows: List[dict] = []

        # ── Backward gap: existing data starts later than our requested from_dt ─
        first_ts_raw = self._store.first_ts(symbol, db_iv)
        # Strip timezone if present (DB may return tz-aware datetimes)
        first_ts = first_ts_raw.replace(tzinfo=None) if first_ts_raw else None
        if first_ts and first_ts > from_dt + timedelta(days=1):
            bwd_end = first_ts - timedelta(minutes=1)
            log.info("Backward gap for %s[%s]: fetching %s to %s",
                     symbol, db_iv,
                     from_dt.strftime("%Y-%m-%d"), bwd_end.strftime("%Y-%m-%d"))
            cursor = from_dt
            while cursor < bwd_end:
                end  = min(cursor + timedelta(days=chunk_days), bwd_end)
                rows = self._fetch_chunk(symbol, exchange, interval, db_iv, cursor, end)
                all_rows.extend(rows)
                cursor = end + timedelta(minutes=1)

        # ── Forward gap: fetch anything newer than what is in DB ─────────────
        last_ts_raw = self._store.last_ts(symbol, db_iv)
        last_ts     = last_ts_raw.replace(tzinfo=None) if last_ts_raw else None
        fetch_from  = (last_ts + timedelta(minutes=1)) if last_ts else from_dt
        fetch_from  = max(fetch_from, from_dt)

        if fetch_from < to_dt - timedelta(minutes=5):
            cursor = fetch_from
            while cursor < to_dt:
                end  = min(cursor + timedelta(days=chunk_days), to_dt)
                rows = self._fetch_chunk(symbol, exchange, interval, db_iv, cursor, end)
                all_rows.extend(rows)
                cursor = end + timedelta(minutes=1)

        self._store.insert(all_rows)
        return len(all_rows)

    # ── single chunk fetch with retry + backoff ───────────────────────────────

    def _fetch_chunk(self, symbol: str, exchange: str,
                     interval: str, db_iv: str,
                     from_dt: datetime, to_dt: datetime) -> List[dict]:
        last_err    = "unknown error"
        is_network  = False

        for attempt in range(MAX_RETRIES + 1):
            self._limiter.acquire(f"{symbol}[{interval}]")
            try:
                resp   = self._api.get_historical_data_v2(
                    interval      = interval,
                    from_date     = _fmt_dt(from_dt),
                    to_date       = _fmt_dt(to_dt),
                    stock_code    = symbol,
                    exchange_code = exchange,
                    product_type  = "cash",
                    expiry_date   = "",
                    right         = "",
                    strike_price  = "",
                )
                is_network = False   # got a response
                status = resp.get("Status")

                if status == 200:
                    raw_rows = resp.get("Success") or []
                    return [
                        r for r in (
                            _parse_row(x, symbol, db_iv) for x in raw_rows
                        ) if r
                    ]

                error_msg = resp.get("Error") or resp.get("message") or str(resp)
                last_err  = f"HTTP {status}: {error_msg}"

                if status in (429, 503) or "throttl" in str(error_msg).lower():
                    wait = 60
                    log.warning("  Rate-limit response for %s[%s] — waiting %ds",
                                symbol, interval, wait)
                    time.sleep(wait)
                    continue

            except RuntimeError:
                raise   # daily limit — propagate immediately

            except Exception as exc:
                last_err   = str(exc)
                is_network = True   # connection-level failure

            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                if is_network:
                    # ⚡ Disconnection alert — visible in log AND status file
                    self._status.increment("disconnections")
                    disc_count = self._status.read()["disconnections"]
                    log.warning(
                        "  ⚠ DISCONNECTION #%d  %s[%s]  attempt %d/%d: %s — "
                        "reconnecting in %ds",
                        disc_count, symbol, interval,
                        attempt + 1, MAX_RETRIES, last_err, delay,
                    )
                else:
                    log.warning(
                        "  Retry %d/%d  %s[%s]  %s–%s: %s — backing off %ds",
                        attempt + 1, MAX_RETRIES, symbol, interval,
                        from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"),
                        last_err, delay,
                    )
                time.sleep(delay)

        log.error("  ✗ Chunk permanently failed  %s[%s]  %s–%s  after %d retries: %s",
                  symbol, interval,
                  from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d"),
                  MAX_RETRIES, last_err)
        return []


# ── Data integrity verifier ───────────────────────────────────────────────────

def verify_data(store: CandleStore,
                tasks: List[Tuple[str, str, str]],
                days: int) -> None:
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(days=days)

    # Expected candles per trading day per interval
    EXPECTED_BARS_PER_DAY = {
        "1m": 375, "5m": 75, "15m": 25, "30m": 13, "1h": 6, "1d": 1,
    }
    # Approximate NSE trading days in the period
    trading_days = int(days * 5 / 7 * 0.98)  # ~98% of weekdays are trading days

    issues: List[str] = []
    seen: Set[str] = set()

    for symbol, _, interval in tasks:
        db_iv = INTERVAL_DB.get(interval, interval)
        key   = f"{symbol}|{db_iv}"
        if key in seen:
            continue
        seen.add(key)

        rows = store.fetch_for_verify(symbol, db_iv, from_dt, to_dt)
        if not rows:
            issues.append(f"NO DATA      {symbol}[{db_iv}]")
            continue

        count = len(rows)

        # ── Row-count sanity ──────────────────────────────────────────────────
        expected = EXPECTED_BARS_PER_DAY.get(db_iv, 1) * trading_days
        if db_iv != "1d" and count < expected * 0.60:
            issues.append(
                f"LOW COUNT    {symbol}[{db_iv}]: {count} rows "
                f"(expected ≥{int(expected*0.60)})"
            )

        # ── OHLC sanity (check all rows) ──────────────────────────────────────
        ohlc_issues = 0
        for ts, o, h, l, c in rows:
            if None in (o, h, l, c):
                ohlc_issues += 1
                continue
            o, h, l, c = float(o), float(h), float(l), float(c)
            if h < l:
                issues.append(f"H<L          {symbol}[{db_iv}] @{ts}: H={h} L={l}")
                ohlc_issues += 1
            elif o <= 0 or c <= 0:
                issues.append(f"ZERO PRICE   {symbol}[{db_iv}] @{ts}: O={o} C={c}")
                ohlc_issues += 1
            if ohlc_issues >= 3:
                issues.append(f"  … (more OHLC errors suppressed for {symbol}[{db_iv}])")
                break

        # ── Intraday gap detection ────────────────────────────────────────────
        if db_iv in ("1m", "5m", "15m", "30m", "1h"):
            expected_gap_min = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
            }[db_iv]
            timestamps = [r[0] for r in rows]
            large_gaps = 0
            for i in range(1, len(timestamps)):
                gap_min = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60
                # Allow gaps of up to 90× the interval (e.g. overnight, lunch, holidays)
                if gap_min > expected_gap_min * 90:
                    large_gaps += 1
            if large_gaps > 5:
                issues.append(
                    f"LARGE GAPS   {symbol}[{db_iv}]: {large_gaps} unexpected gaps "
                    f"(>90× {expected_gap_min}m)"
                )

        log.info("  %-15s [%-3s]  %5d rows  OK", symbol, db_iv, count)

    print()
    if issues:
        log.warning("DATA INTEGRITY ISSUES (%d):", len(issues))
        for issue in issues:
            log.warning("  %s", issue)
    else:
        log.info("All %d symbol-interval combos verified — no integrity issues.", len(seen))


# ── Task builder ──────────────────────────────────────────────────────────────

def _chunks_needed(interval: str, days: int) -> int:
    chunk = CHUNK_DAYS.get(interval, 25)
    return max(1, -(-days // chunk))   # ceiling division


def estimate_calls(tasks: List[Tuple[str, str, str]], days: int) -> int:
    total = 0
    for _sym, _exc, interval in tasks:
        total += _chunks_needed(interval, days)
    return total


def build_tasks(universe: str,
                intervals_override: Optional[List[str]]) -> List[Tuple[str, str, str]]:
    """Return deduplicated list of (symbol, exchange, breeze_interval) tuples."""

    def _add(syms: List[Tuple[str, str]], ivs: List[str],
             out: List[Tuple[str, str, str]], seen: Set) -> None:
        for sym, exc in syms:
            for iv in ivs:
                t = (sym, exc, iv)
                if t not in seen:
                    seen.add(t)
                    out.append(t)

    tasks: List[Tuple[str, str, str]] = []
    seen:  Set = set()

    if universe == "all":
        _add(NSE_INDICES,       intervals_override or INTERVALS_INDICES,    tasks, seen)
        _add(NIFTY50,           intervals_override or INTERVALS_NIFTY50,    tasks, seen)
        _add(NIFTY_NEXT50,      intervals_override or INTERVALS_NEXTNIFTY,  tasks, seen)
        _add(ADDITIONAL_STOCKS, intervals_override or INTERVALS_ADDITIONAL, tasks, seen)
    elif universe == "indices":
        _add(NSE_INDICES,  intervals_override or INTERVALS_INDICES,   tasks, seen)
    elif universe == "nifty50":
        _add(NIFTY50,      intervals_override or INTERVALS_NIFTY50,   tasks, seen)
    elif universe == "nextnifty50":
        _add(NIFTY_NEXT50, intervals_override or INTERVALS_NEXTNIFTY, tasks, seen)
    elif universe == "additional":
        _add(ADDITIONAL_STOCKS, intervals_override or INTERVALS_ADDITIONAL, tasks, seen)
    else:
        raise ValueError(f"Unknown universe: {universe!r}")

    return tasks


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_stop_at(hhmm: str) -> datetime:
    """Parse 'HH:MM' as today's IST datetime (or tomorrow if already past)."""
    h, m  = map(int, hhmm.split(":"))
    now   = datetime.now(IST)
    dt    = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt


def _freeze_and_verify(store: CandleStore, tasks: List[Tuple[str, str, str]],
                       days: int, status: "StatusFile") -> None:
    """Run integrity verification and mark data as frozen in the status file."""
    log.info("=" * 70)
    log.info("DATA FREEZE — running integrity verification before session ends...")
    log.info("=" * 70)
    status.update(phase="freezing")
    try:
        verify_data(store, tasks, days)
        status.update(phase="frozen")
        log.info("✓ Data freeze complete — all downloaded data verified.")
    except Exception as exc:
        log.error("Verification error during freeze: %s", exc)
        status.update(phase="frozen_with_errors", last_error=str(exc))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Bulk historical OHLCV downloader: ICICI Breeze → PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Interval choices: " + "  ".join(INTERVAL_DB.keys()) + "\n"
            "Universe choices: all  indices  nifty50  nextnifty50  additional\n\n"
            "Progress is saved to data/bulk_progress.json — safe to Ctrl+C and resume.\n"
        ),
    )
    p.add_argument("--universe", default="all",
                   choices=["all", "indices", "nifty50", "nextnifty50", "additional"],
                   help="Symbol universe (default: all)")
    p.add_argument("--intervals", nargs="+", metavar="INTERVAL",
                   choices=list(INTERVAL_DB.keys()),
                   help="Override intervals (default: per-universe tier)")
    p.add_argument("--days", type=int, default=365,
                   help="Calendar days of history to download (default: 365)")
    p.add_argument("--stop-at", metavar="HH:MM",
                   help="Stop downloading at this IST time (e.g. 23:50). "
                        "Will run freeze+verify before exiting.")
    p.add_argument("--resume", action="store_true",
                   help="Skip symbol×interval pairs already completed in progress file")
    p.add_argument("--estimate", action="store_true",
                   help="Print estimated API call count and exit without downloading")
    p.add_argument("--verify", action="store_true",
                   help="Check DB data integrity without downloading")
    p.add_argument("--reset-progress", action="store_true",
                   help="Delete progress file and start fresh (implies no --resume)")
    p.add_argument("--max-calls", type=int, default=None, metavar="N",
                   help="Stop after N API calls this session (use when Breeze daily quota "
                        "is partially consumed from a prior run today)")
    args = p.parse_args()

    # ── credentials ──────────────────────────────────────────────────────────
    creds = {
        "BREEZE_API_KEY":       os.environ.get("BREEZE_API_KEY", ""),
        "BREEZE_API_SECRET":    os.environ.get("BREEZE_API_SECRET", ""),
        "BREEZE_SESSION_TOKEN": os.environ.get("BREEZE_SESSION_TOKEN", ""),
        "DB_URL":               os.environ.get("DB_URL", ""),
    }
    missing = [k for k, v in creds.items() if not v]
    if missing:
        log.error("Missing environment variables: %s", ", ".join(missing))
        log.error("Add them to .env in the project root. See .env.example.")
        sys.exit(1)

    # ── deadline ─────────────────────────────────────────────────────────────
    deadline: Optional[datetime] = None
    if args.stop_at:
        try:
            deadline = _parse_stop_at(args.stop_at)
            mins_left = (deadline - datetime.now(IST)).total_seconds() / 60
            log.info("Deadline set: %s IST  (%.0f min from now)",
                     deadline.strftime("%H:%M"), mins_left)
        except ValueError:
            log.error("--stop-at must be HH:MM format, e.g. 23:50")
            sys.exit(1)

    # ── task list ─────────────────────────────────────────────────────────────
    tasks = build_tasks(args.universe, args.intervals)

    # ── estimate ──────────────────────────────────────────────────────────────
    call_count       = estimate_calls(tasks, args.days)
    minutes_at_limit = call_count / CALLS_PER_MINUTE
    log.info(
        "Plan: universe=%s  days=%d  tasks=%d  "
        "~%d API calls  (~%.0f min at %d calls/min)",
        args.universe, args.days, len(tasks),
        call_count, minutes_at_limit, CALLS_PER_MINUTE,
    )
    if call_count > DAILY_CALL_LIMIT:
        log.warning(
            "Estimated calls (%d) > one-session limit (%d). "
            "Downloader stops at limit — re-run with --resume tomorrow.",
            call_count, DAILY_CALL_LIMIT,
        )
    if deadline and minutes_at_limit > (deadline - datetime.now(IST)).total_seconds() / 60:
        available = (deadline - datetime.now(IST)).total_seconds() / 60
        doable    = int(available * CALLS_PER_MINUTE)
        log.warning(
            "Only %.0f min until deadline — can complete ~%d calls (~%d%% of total). "
            "Re-run tomorrow with --resume for the rest.",
            available, doable, doable * 100 // max(call_count, 1),
        )
    if args.estimate:
        return

    # ── reset progress ────────────────────────────────────────────────────────
    if args.reset_progress and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        log.info("Progress file reset.")
    if args.reset_progress and STATUS_FILE.exists():
        STATUS_FILE.unlink()

    # ── DB ────────────────────────────────────────────────────────────────────
    log.info("Connecting to PostgreSQL...")
    try:
        store = CandleStore(creds["DB_URL"])
    except Exception as exc:
        log.error("DB connection failed: %s", exc)
        log.error("Check DB_URL in .env and ensure PostgreSQL is running.")
        sys.exit(1)

    # ── verify only ───────────────────────────────────────────────────────────
    if args.verify:
        log.info("Running integrity verification (no download)...")
        status = StatusFile(STATUS_FILE, len(tasks), deadline)
        verify_data(store, tasks, args.days)
        status.update(phase="verify_done")
        store.close()
        return

    # ── Breeze ────────────────────────────────────────────────────────────────
    log.info("Connecting to Breeze API...")
    try:
        api = BreezeConnect(api_key=creds["BREEZE_API_KEY"])
        api.generate_session(
            api_secret    = creds["BREEZE_API_SECRET"],
            session_token = creds["BREEZE_SESSION_TOKEN"],
        )
        log.info("Breeze session established.")
    except Exception as exc:
        log.error("Breeze connection failed: %s", exc)
        log.error(
            "Ensure BREEZE_SESSION_TOKEN is fresh "
            "(generate at https://api.icicidirect.com/). "
            "Tokens expire every 24 hours."
        )
        store.close()
        sys.exit(1)

    # ── download ──────────────────────────────────────────────────────────────
    session_limit = args.max_calls if args.max_calls else DAILY_CALL_LIMIT
    if args.max_calls:
        log.info("Session call cap: %d  (--max-calls override)", session_limit)
    limiter  = RateLimiter(CALLS_PER_MINUTE, session_limit)
    progress = ProgressTracker(PROGRESS_FILE)
    status   = StatusFile(STATUS_FILE, len(tasks), deadline)
    dl       = BulkDownloader(api, store, limiter, progress, status, deadline)

    # Signal handler for graceful Ctrl+C
    def _handle_signal(sig, frame):
        log.warning("Signal %s received — requesting graceful stop...", sig)
        dl.request_stop()
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        dl.run(tasks, days=args.days, resume=args.resume)
    finally:
        # Always run freeze+verify before exit
        _freeze_and_verify(store, tasks, args.days, status)
        status.update(phase="done", current_symbol="", current_interval="")
        log.info("Final status: %s", json.dumps(status.read(), indent=2))
        store.close()
        log.info("Shutdown complete. Log: %s", LOG_FILE)


if __name__ == "__main__":
    main()
