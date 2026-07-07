#!/usr/bin/env python3
"""
scripts/download_options.py — Download historical option OHLCV candles into the
`options_candles` table (the option analogue of scripts/update_all.py).

For each index underlying it resolves the near expiries and, around the current
ATM, fetches get_historical_data_v2 for each strike × CE/PE × interval and
gap-fills options_candles (idempotent — ON CONFLICT DO UPDATE via the store).

ATM is taken from the latest stored spot close in `candles`. Weekly options list
only ~1–2 weeks out, so history per contract is naturally short.

Usage:
  python scripts/download_options.py                       # defaults below
  python scripts/download_options.py --symbols NIFTY BANKNIFTY FINNIFTY
  python scripts/download_options.py --strikes 10          # ATM ± 10 strikes
  python scripts/download_options.py --expiries weekly monthly
  python scripts/download_options.py --days 20             # look-back window

Defaults: NIFTY + BANKNIFTY, current+next weekly expiry, ATM ± 10 strikes,
intervals 5m/30m/1d, 20-day look-back.
"""
import os, sys, time, logging, argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2, psycopg2.pool
from breeze_connect import BreezeConnect
from trade_engine.symbols import (
    SymbolBuilder, nearest_weekly_expiry, nearest_monthly_expiry, monthly_expiries)

LOG_FILE = ROOT / "logs" / "download_options.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

# Underlying → chain metadata (mirrors app._CHAIN_META / download_chains).
SYMBOL_CFG = {
    "NIFTY":      {"exchange": "NFO", "step": 50,  "friday": False},
    "BANKNIFTY":  {"exchange": "NFO", "step": 100, "friday": False},
    "FINNIFTY":   {"exchange": "NFO", "step": 50,  "friday": False},
    "MIDCPNIFTY": {"exchange": "NFO", "step": 25,  "friday": False},
    "SENSEX":     {"exchange": "BFO", "step": 100, "friday": True},
}

IV_API = {"5m": "5minute", "30m": "30minute", "1d": "1day"}
CHUNK_DAYS = {"5minute": 20, "30minute": 25, "1day": 365}
CALLS_PER_MINUTE = 90

_last_call = 0.0
_call_count = 0


def _rate_limited(fn, *a, **k):
    global _last_call, _call_count
    wait = (60.0 / CALLS_PER_MINUTE) - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    _call_count += 1
    return fn(*a, **k)


def _fmt(dt): return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_dt(raw):
    if not raw:
        return None
    s = str(raw)[:19]
    for f in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _next_friday(today: Optional[date] = None) -> date:
    today = today or date.today()
    days = (4 - today.weekday()) % 7
    if days == 0 and datetime.now().hour >= 15 and datetime.now().minute >= 30:
        days = 7
    return today + timedelta(days=days)


def _expiries_for(symbol: str, weekly: bool, monthly: bool, weekly_n: int) -> List[date]:
    cfg = SYMBOL_CFG.get(symbol.upper(), {})
    out: List[date] = []
    if weekly:
        first = _next_friday() if cfg.get("friday") else nearest_weekly_expiry()
        out += [first + timedelta(weeks=i) for i in range(weekly_n)]
    if monthly:
        for e in monthly_expiries(2):
            if e not in out:
                out.append(e)
    return sorted(set(out))


class Store:
    def __init__(self, url):
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 3, dsn=url)

    def latest_spot(self, symbol: str) -> Optional[float]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT close FROM candles WHERE symbol=%s "
                            "ORDER BY ts DESC LIMIT 1", (symbol,))
                r = cur.fetchone()
                return float(r[0]) if r and r[0] is not None else None
        finally:
            self._pool.putconn(conn)

    def insert(self, rows: List[dict]) -> int:
        if not rows:
            return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    'INSERT INTO options_candles '
                    '(ts, symbol, expiry, strike, "right", "interval", '
                    ' open, high, low, close, volume, oi) VALUES '
                    '(%(ts)s, %(symbol)s, %(expiry)s, %(strike)s, %(right)s, %(interval)s, '
                    ' %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(oi)s) '
                    'ON CONFLICT (symbol, expiry, strike, "right", "interval", ts) DO UPDATE '
                    'SET high=GREATEST(options_candles.high, EXCLUDED.high), '
                    '    low=LEAST(options_candles.low, EXCLUDED.low), '
                    '    close=EXCLUDED.close, volume=EXCLUDED.volume, oi=EXCLUDED.oi', rows)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback(); raise
        finally:
            self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()


def fetch_option(api, symbol, exch, expiry, strike, right_word, iv_api, iv_db,
                 db_right, from_dt, to_dt) -> List[dict]:
    chunk = CHUNK_DAYS.get(iv_api, 20)
    rows, cursor = [], from_dt
    expiry_api = SymbolBuilder.breeze_dt(expiry)
    while cursor < to_dt:
        end = min(cursor + timedelta(days=chunk), to_dt)
        try:
            resp = _rate_limited(
                api.get_historical_data_v2, interval=iv_api,
                from_date=_fmt(cursor), to_date=_fmt(end),
                stock_code=symbol, exchange_code=exch, product_type="options",
                expiry_date=expiry_api, right=right_word, strike_price=str(strike))
        except Exception as exc:
            log.error("    fetch error %s %s %s %s: %s", symbol, strike, db_right, iv_db, exc)
            cursor = end + timedelta(minutes=1)
            continue
        if resp.get("Status") == 200:
            for raw in (resp.get("Success") or []):
                ts = _parse_dt(raw.get("datetime"))
                if not ts:
                    continue
                try:
                    rows.append({
                        "ts": ts, "symbol": symbol, "expiry": expiry, "strike": strike,
                        "right": db_right, "interval": iv_db,
                        "open": float(raw["open"]), "high": float(raw["high"]),
                        "low": float(raw["low"]), "close": float(raw["close"]),
                        "volume": int(float(raw.get("volume", 0) or 0)),
                        "oi": int(float(raw.get("open_interest", 0) or 0)),
                    })
                except (KeyError, TypeError, ValueError):
                    pass
        cursor = end + timedelta(minutes=1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["NIFTY", "BANKNIFTY"],
                    help="Index underlyings (default: NIFTY BANKNIFTY)")
    ap.add_argument("--strikes", type=int, default=10, help="ATM ± N strikes (default 10)")
    ap.add_argument("--expiries", nargs="+", choices=["weekly", "monthly"],
                    default=["weekly"], help="Expiry types (default weekly)")
    ap.add_argument("--weekly-n", type=int, default=2, help="Weekly expiries per symbol (default 2)")
    ap.add_argument("--intervals", nargs="+", default=["5m", "30m", "1d"])
    ap.add_argument("--days", type=int, default=20, help="Look-back window (default 20)")
    args = ap.parse_args()

    store = Store(os.environ["DB_URL"])
    api = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                         session_token=os.environ["BREEZE_SESSION_TOKEN"])
    log.info("Breeze session OK")

    now = datetime.now().replace(second=0, microsecond=0)
    from_dt = now - timedelta(days=args.days)
    weekly = "weekly" in args.expiries
    monthly = "monthly" in args.expiries
    rights = [("call", "CE"), ("put", "PE")]

    grand_total = 0
    for symbol in args.symbols:
        sym = symbol.upper()
        cfg = SYMBOL_CFG.get(sym)
        if not cfg:
            log.warning("No chain config for %s — skipping", sym)
            continue
        spot = store.latest_spot(sym)
        if not spot:
            log.warning("No spot close for %s — skipping", sym)
            continue
        step = cfg["step"]
        atm = round(spot / step) * step
        strikes = [atm + i * step for i in range(-args.strikes, args.strikes + 1)]
        expiries = _expiries_for(sym, weekly, monthly, args.weekly_n)
        log.info("=" * 70)
        log.info("%s  spot=%.1f  ATM=%d  %d strikes (%d..%d)  expiries=%s",
                 sym, spot, atm, len(strikes), strikes[0], strikes[-1],
                 ", ".join(str(e) for e in expiries))
        log.info("=" * 70)
        sym_total = 0
        for expiry in expiries:
            for strike in strikes:
                for right_word, db_right in rights:
                    for iv_db in args.intervals:
                        iv_api = IV_API.get(iv_db)
                        if not iv_api:
                            continue
                        rows = fetch_option(api, sym, cfg["exchange"], expiry, strike,
                                            right_word, iv_api, iv_db, db_right, from_dt, now)
                        n = store.insert(rows)
                        sym_total += n
            log.info("  %s %s: running total +%d  (calls=%d)", sym, expiry, sym_total, _call_count)
        log.info("%s done. +%d option candles.", sym, sym_total)
        grand_total += sym_total

    log.info("=" * 70)
    log.info("ALL DONE. total option candles=%d  calls=%d", grand_total, _call_count)
    log.info("=" * 70)
    store.close()


if __name__ == "__main__":
    main()
