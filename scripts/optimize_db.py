"""
scripts/optimize_db.py — One-time DB performance optimisation.

Applies:
  1. Additional partial / covering indexes on hot query paths
  2. FILLFACTOR adjustments so index pages leave room for updates
  3. VACUUM ANALYZE on all tables
  4. Enables pg_stat_statements for slow-query monitoring
  5. Prints recommended postgresql.conf settings for this machine (40 GB RAM)

Safe to re-run — all DDL uses IF NOT EXISTS / ALTER … IF EXISTS patterns.

Usage:
    python scripts/optimize_db.py
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

# ── Additional indexes beyond what setup_db.py already creates ────────────────
# Goal: cover the exact WHERE + ORDER BY columns the app issues most often.

INDEXES = """
-- spot_ticks: recent-data queries (last N minutes)
CREATE INDEX IF NOT EXISTS idx_spot_ticks_ts
    ON spot_ticks (ts DESC);

-- candles: chart queries — symbol + interval + recent N days
CREATE INDEX IF NOT EXISTS idx_candles_sym_iv_ts_covering
    ON candles (symbol, "interval", ts DESC)
    INCLUDE (open, high, low, close, volume);

-- futures_candles: same pattern
CREATE INDEX IF NOT EXISTS idx_fcandles_sym_exp_iv_ts_cov
    ON futures_candles (symbol, expiry, "interval", ts DESC)
    INCLUDE (open, high, low, close, volume);

-- chain_snapshots: ATM queries (latest snapshot for a symbol+expiry near a strike)
CREATE INDEX IF NOT EXISTS idx_chain_latest
    ON chain_snapshots (symbol, expiry, ts DESC)
    INCLUDE (strike, "right", ltp, iv, delta);

-- chain_snapshots: IV/delta queries across time for a specific strike
CREATE INDEX IF NOT EXISTS idx_chain_strike_ts
    ON chain_snapshots (symbol, expiry, strike, "right", ts DESC)
    INCLUDE (iv, delta, oi);

-- pcr_snapshots: time series for dashboard charts
CREATE INDEX IF NOT EXISTS idx_pcr_sym_exp_ts
    ON pcr_snapshots (symbol, expiry, ts DESC);

-- iv_daily: rank/percentile lookups
CREATE INDEX IF NOT EXISTS idx_iv_daily_sym_date
    ON iv_daily (symbol, date DESC)
    INCLUDE (atm_iv, iv_rank, iv_pctile);
"""

# ── FILLFACTOR: leave free space in pages so HOT updates don't spill ─────────
# candles and futures_candles get UPDATE (high/low merge) — 85% fill is good.
# spot_ticks and chain_snapshots are insert-only — 100% fill is fine.
FILLFACTOR = """
ALTER TABLE candles         SET (fillfactor = 85);
ALTER TABLE futures_candles SET (fillfactor = 85);
"""

# ── VACUUM ANALYZE — reclaim dead rows + refresh planner statistics ───────────
VACUUM_TABLES = [
    "spot_ticks", "candles", "futures_ticks", "futures_candles",
    "chain_snapshots", "depth_snapshots", "pcr_snapshots", "iv_daily",
]

# ── pg_stat_statements — track slow queries ───────────────────────────────────
STAT_STMTS = "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"

# ── Recommended postgresql.conf for 40 GB RAM machine ────────────────────────
CONF_ADVICE = """
Recommended postgresql.conf settings for your 40 GB RAM machine.
File location (Windows): C:\\Program Files\\PostgreSQL\\18\\data\\postgresql.conf
Reload with: SELECT pg_reload_conf();  (no restart needed for most)

  # Memory
  shared_buffers          = 10GB     # 25 %% of RAM
  effective_cache_size    = 30GB     # 75 %% of RAM
  work_mem                = 256MB    # per sort/hash; raise if slow ORDER BY
  maintenance_work_mem    = 2GB      # VACUUM, CREATE INDEX

  # Write throughput
  wal_buffers             = 64MB
  checkpoint_completion_target = 0.9
  synchronous_commit      = off      # faster ticks; tiny replay risk on crash

  # Parallelism
  max_parallel_workers_per_gather = 4
  max_worker_processes    = 8

  # Autovacuum (keep tables lean for tick-heavy workloads)
  autovacuum              = on
  autovacuum_vacuum_scale_factor  = 0.01   # vacuum after 1%% dead rows
  autovacuum_analyze_scale_factor = 0.005  # analyze after 0.5%% new rows

  # Monitoring (requires restart)
  shared_preload_libraries = 'pg_stat_statements'
  pg_stat_statements.track = all
"""


def main() -> None:
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL not set in .env")
        sys.exit(1)

    print(f"Connecting to: {db_url.split('@')[-1]}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True   # DDL + VACUUM need autocommit

    with conn.cursor() as cur:
        # 1. pg_stat_statements
        print("\n[1/4] Enabling pg_stat_statements...")
        try:
            cur.execute(STAT_STMTS)
            print("      [ok] pg_stat_statements")
        except Exception as e:
            print(f"      [skip] {e} (add to shared_preload_libraries and restart)")

        # 2. Additional indexes
        print("\n[2/4] Creating covering indexes...")
        for stmt in [s.strip() for s in INDEXES.split(";") if s.strip()]:
            idx_name = ""
            try:
                if "CREATE INDEX" in stmt:
                    idx_name = stmt.split("idx_")[1].split("\n")[0].strip() if "idx_" in stmt else "?"
                    cur.execute(stmt)
                    print(f"      [ok] idx_{idx_name}")
            except Exception as e:
                print(f"      [err] idx_{idx_name}: {e}")

        # 3. FILLFACTOR
        print("\n[3/4] Setting fillfactor on update-heavy tables...")
        for stmt in [s.strip() for s in FILLFACTOR.split(";") if s.strip()]:
            try:
                cur.execute(stmt)
                tbl = stmt.split("TABLE")[1].split("SET")[0].strip()
                print(f"      [ok] {tbl} fillfactor=85")
            except Exception as e:
                print(f"      [err] {e}")

        # 4. VACUUM ANALYZE
        print("\n[4/4] Running VACUUM ANALYZE on all tables...")
        for tbl in VACUUM_TABLES:
            try:
                cur.execute(f"VACUUM ANALYZE {tbl}")
                print(f"      [ok] {tbl}")
            except Exception as e:
                print(f"      [skip] {tbl}: {e}")

    conn.close()
    print("\n[done] Database optimised.\n")
    print(CONF_ADVICE)


if __name__ == "__main__":
    main()
