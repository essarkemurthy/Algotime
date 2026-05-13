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
-- ─────────────────────────────────────────────
-- Spot ticks: every WebSocket price event
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spot_ticks (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    ltp     NUMERIC(10,2) NOT NULL,
    volume  BIGINT,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_spot_ticks_sym_ts ON spot_ticks (symbol, ts DESC);

-- ─────────────────────────────────────────────
-- 1-minute OHLCV candles (built in-memory from spot ticks)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS candles_1m (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    open    NUMERIC(10,2),
    high    NUMERIC(10,2),
    low     NUMERIC(10,2),
    close   NUMERIC(10,2),
    volume  BIGINT,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_1m_sym_ts ON candles_1m (symbol, ts DESC);

-- ─────────────────────────────────────────────
-- Option chain snapshots (every 5 min, ATM ± N strikes)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chain_snapshots (
    ts      TIMESTAMPTZ   NOT NULL,
    symbol  TEXT          NOT NULL,
    expiry  DATE          NOT NULL,
    strike  INTEGER       NOT NULL,
    right   CHAR(2)       NOT NULL,
    ltp     NUMERIC(10,2),
    oi      BIGINT,
    volume  BIGINT,
    iv      NUMERIC(8,6),
    delta   NUMERIC(8,6),
    gamma   NUMERIC(10,8),
    theta   NUMERIC(8,6),
    vega    NUMERIC(8,6),
    PRIMARY KEY (ts, symbol, expiry, strike, right)
);
CREATE INDEX IF NOT EXISTS idx_chain_sym_expiry_strike
    ON chain_snapshots (symbol, expiry, strike, ts DESC);

-- ─────────────────────────────────────────────
-- Daily ATM IV summary (replaces data/iv_history.csv)
-- ─────────────────────────────────────────────
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
"""


def main() -> None:
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL environment variable is not set.")
        print("       Add it to your .env file:  DB_URL=postgresql://user:pass@localhost:5432/trading_data")
        sys.exit(1)

    print(f"Connecting to: {db_url.split('@')[-1]}")  # hide credentials in output
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
        print("Schema created successfully.")
        print("\nTables ready:")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            for (name,) in cur.fetchall():
                print(f"  ✓ {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
