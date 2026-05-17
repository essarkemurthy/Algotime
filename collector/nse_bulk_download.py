"""
collector/nse_bulk_download.py

Downloads Nifty 50 + Sensex 30 equity and F&O EOD data from NSE public
archives — no Breeze / ICICI credentials needed.

Stores into:
  candles         (interval='1d')  — equity spot OHLCV
  futures_candles (interval='1d')  — futures OHLCV
  options_eod     (new table)      — options OHLCV + OI per strike

Sources (public, no auth):
  Equity : https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  F&O    : https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip

CLI usage:
  python -m collector.nse_bulk_download [--days 730] [--equity-only] [--fo-only]

API usage (from app.py):
  from collector.nse_bulk_download import NSEBulkDownloader
  NSEBulkDownloader(db_url, progress_cb=print).run(days=730)
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import time
import zipfile
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional, Set

import requests

try:
    from .store import DataStore
except ImportError:
    from collector.store import DataStore  # standalone / CLI

log = logging.getLogger(__name__)

# ── Stock universe ─────────────────────────────────────────────────────────────

NIFTY50: List[str] = [
    "ADANIENT",  "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO","BAJAJFINSV", "BAJFINANCE", "BHARTIARTL", "BPCL",
    "BRITANNIA", "CIPLA",      "COALINDIA",  "DIVISLAB",   "DRREDDY",
    "EICHERMOT", "GRASIM",     "HCLTECH",    "HDFCBANK",   "HDFCLIFE",
    "HEROMOTOCO","HINDALCO",   "HINDUNILVR", "ICICIBANK",  "INDUSINDBK",
    "INFY",      "ITC",        "JSWSTEEL",   "KOTAKBANK",  "LT",
    "M&M",       "MARUTI",     "NESTLEIND",  "NTPC",       "ONGC",
    "POWERGRID", "RELIANCE",   "SBILIFE",    "SBIN",       "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL",  "TCS",
    "TECHM",     "TITAN",      "TRENT",      "ULTRACEMCO", "WIPRO",
]

SENSEX30: List[str] = [
    "ADANIPORTS", "AXISBANK",   "BAJAJFINSV", "BAJFINANCE", "BHARTIARTL",
    "HCLTECH",    "HDFCBANK",   "HINDUNILVR", "ICICIBANK",  "INDUSINDBK",
    "INFY",       "ITC",        "JSWSTEEL",   "KOTAKBANK",  "LT",
    "M&M",        "MARUTI",     "NESTLEIND",  "NTPC",       "POWERGRID",
    "RELIANCE",   "SBIN",       "SUNPHARMA",  "TATAMOTORS", "TATASTEEL",
    "TCS",        "TECHM",      "TITAN",      "ULTRACEMCO", "WIPRO",
]

INDEX_FO: List[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

# Deduped combined equity list (Nifty 50 ∪ Sensex 30)
EQUITY_UNIVERSE: List[str] = list(dict.fromkeys(NIFTY50 + SENSEX30))

# Everything we want F&O data for
FO_UNIVERSE: Set[str] = set(EQUITY_UNIVERSE) | set(INDEX_FO)

# ── NSE URLs ───────────────────────────────────────────────────────────────────

_EQ_URL = (
    "https://nsearchives.nseindia.com/products/content/"
    "sec_bhavdata_full_{date}.csv"                       # date = DDMMYYYY
)
_FO_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"        # date = YYYYMMDD
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.nseindia.com/",
    "Connection":      "keep-alive",
}


class NSEBulkDownloader:
    """
    Downloads Nifty 50 + Sensex 30 equity + F&O EOD from NSE public archives.

    Skips weekends and 404 dates (exchange holidays) automatically.
    Already-stored rows are updated (candles, futures_candles) or skipped
    (options_eod via ON CONFLICT DO NOTHING).
    Resumes from the last stored date so re-running is safe and efficient.
    """

    def __init__(
        self,
        db_url: str,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._store = DataStore(db_url)
        self._cb    = progress_cb or log.info
        self._sess  = requests.Session()
        self._sess.headers.update(_HEADERS)
        # Warm up NSE session cookie (prevents 403 on archive requests)
        try:
            self._sess.get("https://www.nseindia.com/", timeout=10)
            time.sleep(0.5)
        except Exception:
            pass

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        days: int = 730,
        equity: bool = True,
        fo: bool = True,
    ) -> None:
        """
        Download up to `days` calendar days of history.
        Set equity=False or fo=False to skip that section.
        """
        self._ensure_tables()

        today     = date.today()
        hard_from = today - timedelta(days=days)

        # Resume from last stored date to avoid re-downloading
        from_date = self._resume_date(hard_from, equity=equity, fo=fo)

        if from_date >= today:
            self._cb("All data already up to date.")
            self._store.close()
            return

        eq_sym  = set(EQUITY_UNIVERSE)
        fo_sym  = FO_UNIVERSE
        trading_days = sum(
            1 for n in range((today - from_date).days)
            if (from_date + timedelta(n)).weekday() < 5
        )

        self._cb(
            f"NSE bulk download: {from_date} → {today - timedelta(days=1)}  "
            f"(~{trading_days} trading days, "
            f"{len(eq_sym)} equity + {len(fo_sym)} F&O symbols)"
        )

        cur = from_date
        done = 0
        while cur < today:
            if cur.weekday() < 5:   # Mon–Fri only
                eq_rows = self._equity_day(cur, eq_sym) if equity else 0
                fut_rows, opt_rows = self._fo_day(cur, fo_sym) if fo else (0, 0)

                if eq_rows + fut_rows + opt_rows > 0:
                    self._cb(
                        f"[{cur}] equity={eq_rows:>4}  "
                        f"futures={fut_rows:>4}  options={opt_rows:>5}"
                    )
                done += 1

            cur += timedelta(days=1)
            time.sleep(0.4)   # ~150 req/min — well below NSE limits

        self._cb(f"Done. {done} calendar-weekdays processed.")
        self._store.close()

    # ── options_eod table setup ───────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        self._store._exec("""
            CREATE TABLE IF NOT EXISTS options_eod (
                date       date          NOT NULL,
                symbol     text          NOT NULL,
                expiry     date          NOT NULL,
                strike     numeric(12,2) NOT NULL,
                "right"    char(2)       NOT NULL,
                open       numeric(12,2),
                high       numeric(12,2),
                low        numeric(12,2),
                close      numeric(12,2),
                settle     numeric(12,2),
                volume     bigint        DEFAULT 0,
                oi         bigint        DEFAULT 0,
                oi_change  bigint        DEFAULT 0,
                underlying numeric(12,2),
                PRIMARY KEY (date, symbol, expiry, strike, "right")
            )
        """)
        self._store._exec(
            "CREATE INDEX IF NOT EXISTS options_eod_sym_exp "
            "ON options_eod (symbol, expiry, date)"
        )
        self._store._exec(
            "CREATE INDEX IF NOT EXISTS options_eod_date ON options_eod (date)"
        )
        log.debug("options_eod table ready.")

    # ── Resume logic ──────────────────────────────────────────────────────────

    def _resume_date(self, hard_from: date, equity: bool, fo: bool) -> date:
        """Return the date to start downloading from (day after last stored date).

        Only resumes if we already have a reasonably complete dataset —
        at least half the target symbols. Avoids false "up to date" when only
        a handful of symbols were loaded from a previous partial run.
        """
        candidates: List[date] = []
        min_eq_symbols = max(len(EQUITY_UNIVERSE) // 2, 5)

        if equity:
            row = self._store._queryone(
                "SELECT COUNT(DISTINCT symbol), MAX(ts::date) "
                "FROM candles WHERE interval='1d'"
            )
            if row and row[1] and (row[0] or 0) >= min_eq_symbols:
                candidates.append(row[1])

        if fo:
            row = self._store._queryone(
                "SELECT COUNT(DISTINCT symbol), MAX(ts::date) "
                "FROM futures_candles WHERE interval='1d'"
            )
            if row and row[1] and (row[0] or 0) >= min_eq_symbols:
                candidates.append(row[1])
            try:
                row = self._store._queryone("SELECT MAX(date) FROM options_eod")
                if row and row[0]:
                    candidates.append(row[0])
            except Exception:
                pass   # table may not exist yet

        if not candidates:
            return hard_from

        last   = min(candidates)          # resume from earliest gap
        resume = last + timedelta(days=1)
        return max(resume, hard_from)     # but not before hard_from

    # ── Equity bhavcopy ───────────────────────────────────────────────────────

    def _equity_day(self, d: date, symbols: Set[str]) -> int:
        raw = self._get(_EQ_URL.format(date=d.strftime("%d%m%Y")))
        if raw is None:
            return 0

        ts     = datetime(d.year, d.month, d.day)
        rows: List[dict] = []
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
        for rec in reader:
            r   = {k.strip(): v.strip() for k, v in rec.items()}
            sym = r.get("SYMBOL", "")
            if r.get("SERIES", "") != "EQ" or sym not in symbols:
                continue
            try:
                rows.append({
                    "ts":       ts,
                    "symbol":   sym,
                    "interval": "1d",
                    "open":     float(r["OPEN_PRICE"]),
                    "high":     float(r["HIGH_PRICE"]),
                    "low":      float(r["LOW_PRICE"]),
                    "close":    float(r["CLOSE_PRICE"]),
                    "volume":   int(float(r.get("TOT_TRAD_QTY", 0) or 0)),
                })
            except (KeyError, ValueError):
                continue

        if rows:
            self._store.insert_candles(rows)
        return len(rows)

    # ── F&O bhavcopy ─────────────────────────────────────────────────────────

    def _fo_day(self, d: date, fo_symbols: Set[str]) -> tuple[int, int]:
        raw = self._get(_FO_URL.format(date=d.strftime("%Y%m%d")))
        if raw is None:
            return 0, 0

        try:
            zf   = zipfile.ZipFile(io.BytesIO(raw))
            text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("F&O zip parse %s: %s", d, exc)
            return 0, 0

        ts        = datetime(d.year, d.month, d.day)
        fut_rows: List[dict] = []
        opt_rows: List[dict] = []

        reader = csv.DictReader(io.StringIO(text))
        for rec in reader:
            sym = rec.get("TckrSymb", "").strip()
            if sym not in fo_symbols:
                continue

            instr = rec.get("FinInstrmTp", "").strip()
            optn  = rec.get("OptnTp", "").strip()

            # Classify as futures or options
            if instr in ("STF", "IDF"):
                kind = "futures"
            elif instr in ("STO", "IDO"):
                kind = "options"
            elif optn in ("CE", "PE"):
                kind = "options"
            elif not optn or optn in ("-", "XX"):
                kind = "futures"
            else:
                continue

            try:
                expiry = _parse_date(rec.get("XpryDt", ""))
                if expiry is None:
                    continue

                opn  = _f(rec.get("OpnPric"))
                hgh  = _f(rec.get("HghPric"))
                low  = _f(rec.get("LwPric"))
                cls  = _f(rec.get("ClsPric"))
                sett = _f(rec.get("SttlmPric"))
                vol  = int(float(rec.get("TtlTradgVol", 0) or 0))
                oi   = int(float(rec.get("OpnIntrst", 0) or 0))
                # Use settlement as close when close is 0 (no trades that day)
                close = cls if cls > 0 else sett

                if kind == "futures":
                    fut_rows.append({
                        "ts":       ts,
                        "symbol":   sym,
                        "expiry":   expiry,
                        "interval": "1d",
                        "open":     opn,
                        "high":     hgh,
                        "low":      low,
                        "close":    close,
                        "volume":   vol,
                    })
                else:
                    strike = _f(rec.get("StrkPric"))
                    if not strike or optn not in ("CE", "PE"):
                        continue
                    opt_rows.append({
                        "date":      d,
                        "symbol":    sym,
                        "expiry":    expiry,
                        "strike":    strike,
                        "right":     optn,
                        "open":      opn,
                        "high":      hgh,
                        "low":       low,
                        "close":     close,
                        "settle":    sett,
                        "volume":    vol,
                        "oi":        oi,
                        "oi_change": int(float(rec.get("ChngInOpnIntrst", 0) or 0)),
                        "underlying":_f(rec.get("UndrlygPric")),
                    })
            except Exception as exc:
                log.debug("F&O row parse %s %s: %s", d, sym, exc)

        if fut_rows:
            self._store.insert_futures_candles(fut_rows)
        if opt_rows:
            self._store.insert_options_eod(opt_rows)

        return len(fut_rows), len(opt_rows)

    # ── HTTP helper with retry ────────────────────────────────────────────────

    def _get(self, url: str, retries: int = 3) -> Optional[bytes]:
        for attempt in range(retries):
            try:
                r = self._sess.get(url, timeout=30)
                if r.status_code == 404:
                    return None   # holiday / file not yet published
                r.raise_for_status()
                return r.content
            except requests.HTTPError:
                return None
            except Exception as exc:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    log.warning("GET failed %s: %s", url, exc)
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(raw) -> Optional[date]:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt, length in (
        ("%Y-%m-%d", 10),
        ("%d-%b-%Y", 11),
        ("%d/%m/%Y", 10),
        ("%Y%m%d",   8),
    ):
        try:
            return datetime.strptime(s[:length], fmt).date()
        except ValueError:
            continue
    return None


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    p = argparse.ArgumentParser(description="Download NSE EOD data into PostgreSQL")
    p.add_argument("--days",        type=int, default=730,
                   help="Calendar days of history (default 730 ≈ 2 years)")
    p.add_argument("--db-url",      default=os.environ.get("DB_URL"),
                   help="PostgreSQL DSN (defaults to DB_URL env var)")
    p.add_argument("--equity-only", action="store_true",
                   help="Skip F&O download")
    p.add_argument("--fo-only",     action="store_true",
                   help="Skip equity download")
    args = p.parse_args()

    if not args.db_url:
        print("ERROR: --db-url or DB_URL env var is required.")
        raise SystemExit(1)

    NSEBulkDownloader(
        db_url=args.db_url,
        progress_cb=print,
    ).run(
        days=args.days,
        equity=not args.fo_only,
        fo=not args.equity_only,
    )


if __name__ == "__main__":
    _main()
