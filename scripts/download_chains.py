#!/usr/bin/env python3
"""
scripts/download_chains.py — Download and store option chain snapshots for
NIFTY, BANKNIFTY, SENSEX, and FINNIFTY to the chain_snapshots DB table.

Usage:
  python scripts/download_chains.py              # one snapshot, all 4 symbols
  python scripts/download_chains.py --loop       # repeat every 5 min (market hours)
  python scripts/download_chains.py --symbols NIFTY BANKNIFTY   # specific symbols
  python scripts/download_chains.py --expiries weekly monthly    # expiry types

Requires BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN, DB_URL in .env
"""

import os
import sys
import time
import logging
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import psycopg2
import psycopg2.pool
import numpy as np
import pandas as pd
from breeze_connect import BreezeConnect

from trade_engine.symbols import (
    SymbolBuilder, nearest_weekly_expiry, nearest_monthly_expiry, monthly_expiries,
)

LOG_FILE = ROOT / "logs" / "download_chains.log"
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

# ── Symbol configuration ──────────────────────────────────────────────────────
SYMBOL_CFG = {
    "NIFTY":      {"exchange": "NFO", "step": 50,  "weekly": True},
    "BANKNIFTY":  {"exchange": "NFO", "step": 100, "weekly": True},
    "SENSEX":     {"exchange": "BFO", "step": 100, "weekly": True,  "friday": True},
    "FINNIFTY":   {"exchange": "NFO", "step": 50,  "weekly": True},
    "MIDCPNIFTY": {"exchange": "NFO", "step": 25,  "weekly": True},
}

# ── Expiry helpers ────────────────────────────────────────────────────────────

def _next_friday(today: Optional[date] = None) -> date:
    today = today or date.today()
    days  = (4 - today.weekday()) % 7
    if days == 0 and datetime.now().hour >= 15 and datetime.now().minute >= 30:
        days = 7
    return today + timedelta(days=days)


def _expiries_for(symbol: str, include_weekly: bool, include_monthly: bool,
                  weekly_n: int = 4) -> List[date]:
    cfg = SYMBOL_CFG.get(symbol.upper(), {})
    result = []
    if include_weekly and cfg.get("weekly"):
        if cfg.get("friday"):
            first = _next_friday()
            result += [first + timedelta(weeks=i) for i in range(weekly_n)]
        else:
            first = nearest_weekly_expiry()
            result += [first + timedelta(weeks=i) for i in range(weekly_n)]
    if include_monthly:
        seen = set(result)
        for exp in monthly_expiries(3):
            if exp not in seen:
                result.append(exp)
                seen.add(exp)
    return sorted(set(result))


# ── DB store ──────────────────────────────────────────────────────────────────

class ChainStore:
    def __init__(self, db_url: str) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(1, 4, dsn=db_url)

    def insert(self, rows: List[dict]) -> int:
        if not rows:
            return 0
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO chain_snapshots
                        (ts, symbol, expiry, strike, "right",
                         ltp, bid, ask, oi, volume, iv, delta, gamma, theta, vega)
                    VALUES
                        (%(ts)s, %(symbol)s, %(expiry)s, %(strike)s, %(right)s,
                         %(ltp)s, %(bid)s, %(ask)s, %(oi)s, %(volume)s,
                         %(iv)s, %(delta)s, %(gamma)s, %(theta)s, %(vega)s)
                    ON CONFLICT DO NOTHING""", rows)
            conn.commit()
            return len(rows)
        except Exception:
            conn.rollback(); raise
        finally:
            self._pool.putconn(conn)

    def insert_pcr(self, row: dict) -> None:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO pcr_snapshots (ts, symbol, expiry, call_oi, put_oi, pcr)
                    VALUES (%(ts)s, %(symbol)s, %(expiry)s, %(call_oi)s, %(put_oi)s, %(pcr)s)
                    ON CONFLICT DO NOTHING""", row)
            conn.commit()
        except Exception:
            conn.rollback()
            log.warning("PCR insert skipped (table may not exist): %s", row)
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        self._pool.closeall()


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def _nan_or(val) -> Optional[float]:
    try:
        f = float(val)
        return None if (isinstance(f, float) and np.isnan(f)) else f
    except (TypeError, ValueError):
        return None


def fetch_chain(api: BreezeConnect, symbol: str, expiry: date) -> pd.DataFrame:
    cfg  = SYMBOL_CFG.get(symbol.upper(), {"exchange": "NFO"})
    resp = api.get_option_chain_quotes(
        stock_code    = symbol.upper(),
        exchange_code = cfg["exchange"],
        product_type  = "options",
        expiry_date   = SymbolBuilder.breeze_dt(expiry),
        right         = "others",
        strike_price  = "0",
    )
    if resp.get("Status") != 200:
        log.warning("Chain fetch failed %s %s: %s", symbol, expiry, resp.get("Error", resp))
        return pd.DataFrame()
    rows = resp.get("Success") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["strike_price"]     = pd.to_numeric(df["strike_price"], errors="coerce")
    df["ltp"]              = pd.to_numeric(df["ltp"],              errors="coerce")
    df["open_interest"]    = pd.to_numeric(df["open_interest"],    errors="coerce")
    df["volume"]           = pd.to_numeric(df["volume"],           errors="coerce")
    df["best_bid_price"]   = pd.to_numeric(df.get("best_bid_price",   0), errors="coerce")
    df["best_offer_price"] = pd.to_numeric(df.get("best_offer_price", 0), errors="coerce")
    df["right"]            = df["right"].str.lower().str.strip()
    return df.dropna(subset=["strike_price", "ltp"]).reset_index(drop=True)


def build_rows(df: pd.DataFrame, symbol: str, expiry: date, ts: datetime) -> List[dict]:
    rows = []
    for row in df.itertuples():
        right = "CE" if str(getattr(row, "right", "")).startswith("c") else "PE"
        rows.append({
            "ts":     ts,
            "symbol": symbol.upper(),
            "expiry": expiry,
            "strike": int(float(row.strike_price)),
            "right":  right,
            "ltp":    _nan_or(row.ltp),
            "bid":    _nan_or(getattr(row, "best_bid_price",   None)),
            "ask":    _nan_or(getattr(row, "best_offer_price", None)),
            "oi":     int(float(row.open_interest)) if _nan_or(row.open_interest) is not None else None,
            "volume": int(float(row.volume))        if _nan_or(row.volume)        is not None else None,
            "iv":     None, "delta": None, "gamma": None, "theta": None, "vega": None,
        })
    return rows


# ── Main snapshot loop ────────────────────────────────────────────────────────

def run_snapshot(api: BreezeConnect, store: ChainStore,
                 symbols: List[str], include_weekly: bool, include_monthly: bool) -> int:
    ts    = datetime.now().astimezone()
    total = 0

    for sym in symbols:
        expiries = _expiries_for(sym, include_weekly, include_monthly)
        if not expiries:
            log.warning("No expiries for %s — skipping", sym)
            continue

        log.info("%-12s  %d expiries: %s", sym, len(expiries),
                 ", ".join(str(e) for e in expiries))

        for expiry in expiries:
            try:
                time.sleep(0.5)   # gentle rate limit between calls
                chain = fetch_chain(api, sym, expiry)
                if chain.empty:
                    log.info("  %s %s — empty chain (expiry may not be listed)", sym, expiry)
                    continue

                rows  = build_rows(chain, sym, expiry, ts)
                n     = store.insert(rows)
                total += n

                # PCR
                ce_oi = int(chain.loc[chain["right"].str.startswith("c"), "open_interest"].fillna(0).sum())
                pe_oi = int(chain.loc[chain["right"].str.startswith("p"), "open_interest"].fillna(0).sum())
                pcr   = round(pe_oi / ce_oi, 4) if ce_oi else None
                store.insert_pcr({"ts": ts, "symbol": sym.upper(), "expiry": expiry,
                                  "call_oi": ce_oi, "put_oi": pe_oi, "pcr": pcr})

                log.info("  ✓ %s  expiry=%-12s  rows=%-4d  ce_oi=%8d  pe_oi=%8d  pcr=%s",
                         sym, expiry, n, ce_oi, pe_oi,
                         f"{pcr:.2f}" if pcr else "n/a")
            except Exception as exc:
                log.error("  ✗ %s %s: %s", sym, expiry, exc)

    return total


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Download option chain snapshots → PostgreSQL")
    ap.add_argument("--symbols", nargs="+",
                    default=["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"],
                    metavar="SYM",
                    help="Symbols to fetch (default: NIFTY BANKNIFTY SENSEX FINNIFTY)")
    ap.add_argument("--expiries", nargs="+", choices=["weekly", "monthly"],
                    default=["weekly"],
                    help="Expiry types to collect (default: weekly)")
    ap.add_argument("--loop", action="store_true",
                    help="Repeat every --interval seconds until Ctrl+C")
    ap.add_argument("--interval", type=int, default=300,
                    help="Seconds between snapshots in loop mode (default: 300)")
    ap.add_argument("--weekly-n", type=int, default=4,
                    help="Number of weekly expiries to fetch per symbol (default: 4)")
    args = ap.parse_args()

    include_weekly  = "weekly"  in args.expiries
    include_monthly = "monthly" in args.expiries

    creds = {k: os.environ.get(k, "") for k in
             ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN", "DB_URL"]}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        log.error("Missing env vars: %s  —  check .env", ", ".join(missing))
        sys.exit(1)

    log.info("=" * 70)
    log.info("CHAIN SNAPSHOT DOWNLOADER")
    log.info("Symbols: %s", " ".join(args.symbols))
    log.info("Expiries: %s  |  Weekly-n: %d  |  Loop: %s",
             " + ".join(args.expiries), args.weekly_n, args.loop)
    log.info("=" * 70)

    log.info("Connecting to PostgreSQL…")
    store = ChainStore(creds["DB_URL"])

    log.info("Connecting to Breeze API…")
    api = BreezeConnect(api_key=creds["BREEZE_API_KEY"])
    api.generate_session(api_secret=creds["BREEZE_API_SECRET"],
                         session_token=creds["BREEZE_SESSION_TOKEN"])
    log.info("Breeze session OK")

    run_count = 0
    while True:
        run_count += 1
        log.info("─── Snapshot #%d  %s ───", run_count,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        n = run_snapshot(api, store, args.symbols, include_weekly, include_monthly)
        log.info("Snapshot #%d complete — %d rows inserted", run_count, n)

        if not args.loop:
            break

        log.info("Sleeping %ds before next snapshot…", args.interval)
        time.sleep(args.interval)

    store.close()
    log.info("Done. Log: %s", LOG_FILE)


if __name__ == "__main__":
    main()
