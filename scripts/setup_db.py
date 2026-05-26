"""
scripts/setup_db.py — One-time database schema creation.

Run once after installing PostgreSQL and setting DB_URL in .env:
    python scripts/setup_db.py

Safe to re-run; all CREATE statements use IF NOT EXISTS.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import psycopg2

SCHEMA = """
-- ─────────────────────────────────────────────────────────────────────────────
-- Spot ticks: every WebSocket price event for equity / index cash segment
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spot_ticks (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    ltp     NUMERIC(10,2) NOT NULL,
    volume  BIGINT,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_spot_ticks_sym_ts ON spot_ticks (symbol, ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Candles: unified OHLCV for all intervals and equity/index spot
-- interval: '1m', '5m', '15m', '1d'
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS candles (
    ts       TIMESTAMPTZ   NOT NULL,
    symbol   TEXT          NOT NULL,
    "interval" TEXT        NOT NULL,
    open     NUMERIC(10,2),
    high     NUMERIC(10,2),
    low      NUMERIC(10,2),
    close    NUMERIC(10,2),
    volume   BIGINT,
    PRIMARY KEY (symbol, "interval", ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_sym_iv_ts ON candles (symbol, "interval", ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Futures ticks: WebSocket price events for futures contracts
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS futures_ticks (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    expiry  DATE          NOT NULL,
    ltp     NUMERIC(10,2),
    oi      BIGINT,
    volume  BIGINT,
    PRIMARY KEY (symbol, expiry, ts)
);
CREATE INDEX IF NOT EXISTS idx_fticks_sym_exp_ts ON futures_ticks (symbol, expiry, ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Futures candles: OHLCV for futures (built from ticks + REST historical)
-- interval: '1m', '5m', '15m', '1d'
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS futures_candles (
    ts       TIMESTAMPTZ   NOT NULL,
    symbol   TEXT          NOT NULL,
    expiry   DATE          NOT NULL,
    "interval" TEXT        NOT NULL,
    open     NUMERIC(10,2),
    high     NUMERIC(10,2),
    low      NUMERIC(10,2),
    close    NUMERIC(10,2),
    volume   BIGINT,
    PRIMARY KEY (symbol, expiry, "interval", ts)
);
CREATE INDEX IF NOT EXISTS idx_fcandles_sym_exp_iv_ts
    ON futures_candles (symbol, expiry, "interval", ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Option chain snapshots: every 5 min, all strikes, all near expiries
-- Includes bid/ask and full Greeks
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chain_snapshots (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    expiry  DATE          NOT NULL,
    strike  INTEGER       NOT NULL,
    "right" CHAR(2)       NOT NULL,
    ltp     NUMERIC(10,2),
    bid     NUMERIC(10,2),
    ask     NUMERIC(10,2),
    oi      BIGINT,
    volume  BIGINT,
    iv      NUMERIC(8,6),
    delta   NUMERIC(8,6),
    gamma   NUMERIC(10,8),
    theta   NUMERIC(8,6),
    vega    NUMERIC(8,6),
    PRIMARY KEY (ts, symbol, expiry, strike, "right")
);
CREATE INDEX IF NOT EXISTS idx_chain_sym_expiry_strike
    ON chain_snapshots (symbol, expiry, strike, ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Market depth snapshots: 5-level bid/ask order book
-- side: 'B' = bid, 'A' = ask  |  level: 1 (best) to 5
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS depth_snapshots (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    side    CHAR(1)       NOT NULL,
    level   SMALLINT      NOT NULL,
    price   NUMERIC(10,2),
    qty     INTEGER,
    PRIMARY KEY (ts, symbol, side, level)
);
CREATE INDEX IF NOT EXISTS idx_depth_sym_ts ON depth_snapshots (symbol, ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- PCR snapshots: put-call ratio per expiry, computed from chain OI
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pcr_snapshots (
    ts       TIMESTAMPTZ   NOT NULL,
    symbol   TEXT          NOT NULL,
    expiry   DATE          NOT NULL,
    call_oi  BIGINT,
    put_oi   BIGINT,
    pcr      NUMERIC(8,4),
    PRIMARY KEY (ts, symbol, expiry)
);
CREATE INDEX IF NOT EXISTS idx_pcr_sym_ts ON pcr_snapshots (symbol, ts DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Daily ATM IV summary — used for IV Rank / Percentile calculation
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS iv_daily (
    date        DATE          NOT NULL,
    symbol      TEXT          NOT NULL,
    expiry      DATE          NOT NULL,
    atm_strike  INTEGER,
    atm_iv      NUMERIC(8,6),
    iv_rank     NUMERIC(5,2),
    iv_pctile   NUMERIC(5,2),
    PRIMARY KEY (date, symbol, expiry)
);
CREATE INDEX IF NOT EXISTS idx_iv_daily_sym ON iv_daily (symbol, date DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Download audit log — tracks every bulk_download.py run per symbol×interval
-- status: 'ok' | 'error' | 'daily_limit'
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS download_log (
    id             BIGSERIAL     PRIMARY KEY,
    ts             TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    symbol         TEXT          NOT NULL,
    "interval"     TEXT          NOT NULL,
    rows_inserted  INTEGER       NOT NULL DEFAULT 0,
    status         TEXT          NOT NULL,
    note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_dllog_sym_iv ON download_log (symbol, "interval", ts DESC);
"""


def main() -> None:
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL environment variable is not set.")
        print("       Add it to your .env:  DB_URL=postgresql://user:pass@localhost:5432/market_data")
        sys.exit(1)

    print(f"Connecting to: {db_url.split('@')[-1]}")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
        print("Schema created successfully.\n")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            print("Tables ready:")
            for (name,) in cur.fetchall():
                print(f"  [ok] {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
