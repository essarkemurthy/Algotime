import logging
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
import psycopg2
import psycopg2.pool

log = logging.getLogger(__name__)


class DataStore:
    """
    Thread-safe PostgreSQL store backed by a connection pool.
    All public methods acquire a connection, execute, commit, and return it.
    """

    def __init__(self, db_url: str) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=db_url
        )
        log.info("DataStore connected to PostgreSQL.")

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get(self):
        return self._pool.getconn()

    def _put(self, conn) -> None:
        self._pool.putconn(conn)

    def _exec(self, sql: str, params=None) -> None:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put(conn)

    def _execmany(self, sql: str, rows: list) -> None:
        if not rows:
            return
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put(conn)

    # ── spot ticks ────────────────────────────────────────────────────────────

    def insert_spot_ticks(self, rows: List[Dict]) -> None:
        self._execmany(
            """INSERT INTO spot_ticks (ts, symbol, ltp, volume)
               VALUES (%(ts)s, %(symbol)s, %(ltp)s, %(volume)s)
               ON CONFLICT DO NOTHING""",
            rows,
        )

    # ── 1-min candles ─────────────────────────────────────────────────────────

    def insert_candle(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO candles_1m (ts, symbol, open, high, low, close, volume)
               VALUES (%(ts)s, %(symbol)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
               ON CONFLICT (symbol, ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(candles_1m.high, EXCLUDED.high),
                   low    = LEAST(candles_1m.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            row,
        )

    def insert_candles(self, rows: List[Dict]) -> None:
        for row in rows:
            self.insert_candle(row)

    # ── chain snapshots ───────────────────────────────────────────────────────

    def insert_chain_snapshots(self, rows: List[Dict]) -> None:
        self._execmany(
            """INSERT INTO chain_snapshots
                   (ts, symbol, expiry, strike, right,
                    ltp, oi, volume, iv, delta, gamma, theta, vega)
               VALUES
                   (%(ts)s, %(symbol)s, %(expiry)s, %(strike)s, %(right)s,
                    %(ltp)s, %(oi)s, %(volume)s,
                    %(iv)s, %(delta)s, %(gamma)s, %(theta)s, %(vega)s)
               ON CONFLICT DO NOTHING""",
            rows,
        )

    # ── EOD IV daily ──────────────────────────────────────────────────────────

    def insert_iv_daily(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO iv_daily
                   (date, symbol, expiry, atm_strike, atm_iv, iv_rank, iv_pctile)
               VALUES
                   (%(date)s, %(symbol)s, %(expiry)s, %(atm_strike)s,
                    %(atm_iv)s, %(iv_rank)s, %(iv_pctile)s)
               ON CONFLICT (date, symbol, expiry) DO UPDATE
               SET atm_strike = EXCLUDED.atm_strike,
                   atm_iv     = EXCLUDED.atm_iv,
                   iv_rank    = EXCLUDED.iv_rank,
                   iv_pctile  = EXCLUDED.iv_pctile""",
            row,
        )

    def get_iv_history(self, symbol: str, lookback_days: int = 252) -> pd.DataFrame:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT date, atm_iv FROM iv_daily
                       WHERE symbol = %s
                       ORDER BY date DESC
                       LIMIT %s""",
                    (symbol, lookback_days),
                )
                rows = cur.fetchall()
            return pd.DataFrame(rows, columns=["date", "atm_iv"])
        finally:
            self._put(conn)

    def get_last_atm_iv(
        self, symbol: str, expiry: date, trade_date: date
    ) -> Optional[Dict]:
        """
        Returns {atm_strike, atm_iv} from the most recent chain snapshot
        of trade_date, selecting the CE row whose delta is closest to 0.5 (≈ ATM).
        """
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH last_ts AS (
                        SELECT MAX(ts) AS max_ts
                        FROM chain_snapshots
                        WHERE symbol = %s AND expiry = %s AND ts::date = %s
                    )
                    SELECT cs.strike, cs.iv
                    FROM   chain_snapshots cs, last_ts
                    WHERE  cs.symbol = %s
                      AND  cs.expiry = %s
                      AND  cs.ts     = last_ts.max_ts
                      AND  cs.right  = 'CE'
                      AND  cs.iv     IS NOT NULL
                      AND  cs.delta  IS NOT NULL
                    ORDER BY ABS(cs.delta - 0.5)
                    LIMIT 1
                    """,
                    (symbol, expiry, trade_date, symbol, expiry),
                )
                row = cur.fetchone()
            return {"atm_strike": row[0], "atm_iv": row[1]} if row else None
        finally:
            self._put(conn)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._pool.closeall()
        log.info("DataStore connection pool closed.")
