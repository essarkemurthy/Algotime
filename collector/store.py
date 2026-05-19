import logging
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd
import psycopg2
import psycopg2.pool
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)


class DataStore:
    """
    Thread-safe PostgreSQL store backed by a connection pool.
    All public methods acquire a connection, execute, commit, and return it.
    Uses execute_values for batch inserts (single multi-row statement, 10-100x
    faster than executemany which issues one round-trip per row).
    """

    def __init__(self, db_url: str) -> None:
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=4, maxconn=20, dsn=db_url
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

    def _execvalues(self, sql: str, rows: list, template: str) -> None:
        """Single multi-row INSERT via execute_values — much faster than executemany."""
        if not rows:
            return
        conn = self._get()
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows, template=template, page_size=500)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put(conn)

    def _queryone(self, sql: str, params=None):
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
        finally:
            self._put(conn)

    def _queryall(self, sql: str, params=None) -> list:
        conn = self._get()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            self._put(conn)

    # ── spot ticks ────────────────────────────────────────────────────────────

    def insert_spot_ticks(self, rows: List[Dict]) -> None:
        self._execvalues(
            """INSERT INTO spot_ticks (ts, symbol, ltp, volume)
               VALUES %s ON CONFLICT DO NOTHING""",
            [(r["ts"], r["symbol"], r["ltp"], r["volume"]) for r in rows],
            template="(%s, %s, %s, %s)",
        )

    # ── candles (unified: equity spot, all intervals) ─────────────────────────

    def insert_candle(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
               VALUES (%(ts)s, %(symbol)s, %(interval)s,
                       %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
               ON CONFLICT (symbol, "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(candles.high, EXCLUDED.high),
                   low    = LEAST(candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            row,
        )

    def insert_candles(self, rows: List[Dict]) -> None:
        if not rows:
            return
        self._execvalues(
            """INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
               VALUES %s
               ON CONFLICT (symbol, "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(candles.high, EXCLUDED.high),
                   low    = LEAST(candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            [(r["ts"], r["symbol"], r["interval"],
              r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
            template="(%s, %s, %s, %s, %s, %s, %s, %s)",
        )

    def get_candle_last_ts(self, symbol: str, interval: str) -> Optional[datetime]:
        row = self._queryone(
            'SELECT MAX(ts) FROM candles WHERE symbol=%s AND "interval"=%s',
            (symbol, interval),
        )
        return row[0] if row else None

    # ── futures ticks ─────────────────────────────────────────────────────────

    def insert_futures_ticks(self, rows: List[Dict]) -> None:
        self._execmany(
            """INSERT INTO futures_ticks (ts, symbol, expiry, ltp, oi, volume)
               VALUES (%(ts)s, %(symbol)s, %(expiry)s, %(ltp)s, %(oi)s, %(volume)s)
               ON CONFLICT DO NOTHING""",
            rows,
        )

    # ── futures candles ───────────────────────────────────────────────────────

    def insert_futures_candle(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO futures_candles
                   (ts, symbol, expiry, "interval", open, high, low, close, volume)
               VALUES
                   (%(ts)s, %(symbol)s, %(expiry)s, %(interval)s,
                    %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
               ON CONFLICT (symbol, expiry, "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(futures_candles.high, EXCLUDED.high),
                   low    = LEAST(futures_candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            row,
        )

    def insert_futures_candles(self, rows: List[Dict]) -> None:
        if not rows:
            return
        self._execvalues(
            """INSERT INTO futures_candles
                   (ts, symbol, expiry, "interval", open, high, low, close, volume)
               VALUES %s
               ON CONFLICT (symbol, expiry, "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(futures_candles.high, EXCLUDED.high),
                   low    = LEAST(futures_candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            [(r["ts"], r["symbol"], r["expiry"], r["interval"],
              r["open"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        )

    def get_futures_candle_last_ts(self, symbol: str, expiry: date,
                                   interval: str) -> Optional[datetime]:
        row = self._queryone(
            'SELECT MAX(ts) FROM futures_candles WHERE symbol=%s AND expiry=%s AND "interval"=%s',
            (symbol, expiry, interval),
        )
        return row[0] if row else None

    # ── option chain snapshots ────────────────────────────────────────────────

    def insert_chain_snapshots(self, rows: List[Dict]) -> None:
        self._execmany(
            """INSERT INTO chain_snapshots
                   (ts, symbol, expiry, strike, "right",
                    ltp, bid, ask, oi, volume, iv, delta, gamma, theta, vega)
               VALUES
                   (%(ts)s, %(symbol)s, %(expiry)s, %(strike)s, %(right)s,
                    %(ltp)s, %(bid)s, %(ask)s, %(oi)s, %(volume)s,
                    %(iv)s, %(delta)s, %(gamma)s, %(theta)s, %(vega)s)
               ON CONFLICT DO NOTHING""",
            rows,
        )

    # ── market depth snapshots ────────────────────────────────────────────────

    def insert_depth_snapshots(self, rows: List[Dict]) -> None:
        self._execmany(
            """INSERT INTO depth_snapshots (ts, symbol, side, level, price, qty)
               VALUES (%(ts)s, %(symbol)s, %(side)s, %(level)s, %(price)s, %(qty)s)
               ON CONFLICT DO NOTHING""",
            rows,
        )

    # ── PCR snapshots ─────────────────────────────────────────────────────────

    def insert_pcr_snapshot(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO pcr_snapshots (ts, symbol, expiry, call_oi, put_oi, pcr)
               VALUES (%(ts)s, %(symbol)s, %(expiry)s, %(call_oi)s, %(put_oi)s, %(pcr)s)
               ON CONFLICT DO NOTHING""",
            row,
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
        rows = self._queryall(
            """SELECT date, atm_iv FROM iv_daily
               WHERE symbol = %s
               ORDER BY date DESC
               LIMIT %s""",
            (symbol, lookback_days),
        )
        return pd.DataFrame(rows, columns=["date", "atm_iv"])

    def get_last_atm_iv(self, symbol: str, expiry: date,
                        trade_date: date) -> Optional[Dict]:
        row = self._queryone(
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
              AND  cs."right"  = 'CE'
              AND  cs.iv     IS NOT NULL
              AND  cs.delta  IS NOT NULL
            ORDER BY ABS(cs.delta - 0.5)
            LIMIT 1
            """,
            (symbol, expiry, trade_date, symbol, expiry),
        )
        return {"atm_strike": row[0], "atm_iv": row[1]} if row else None

    # ── options EOD ───────────────────────────────────────────────────────────

    def insert_options_eod(self, rows: List[Dict]) -> None:
        if not rows:
            return
        self._execvalues(
            """INSERT INTO options_eod
                   (date, symbol, expiry, strike, "right",
                    open, high, low, close, settle,
                    volume, oi, oi_change, underlying)
               VALUES %s
               ON CONFLICT (date, symbol, expiry, strike, "right") DO NOTHING""",
            [(r["date"], r["symbol"], r["expiry"], r["strike"], r["right"],
              r.get("open"), r.get("high"), r.get("low"), r.get("close"),
              r.get("settle"), r.get("volume", 0), r.get("oi", 0),
              r.get("oi_change", 0), r.get("underlying")) for r in rows],
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        )

    def get_options_eod(
        self,
        symbol: str,
        expiry: date,
        trade_date: Optional[date] = None,
    ) -> List[Dict]:
        if trade_date:
            rows = self._queryall(
                """SELECT date, strike, "right", open, high, low, close,
                          settle, volume, oi, oi_change, underlying
                   FROM options_eod
                   WHERE symbol=%s AND expiry=%s AND date=%s
                   ORDER BY strike, "right" """,
                (symbol, expiry, trade_date),
            )
        else:
            rows = self._queryall(
                """SELECT date, strike, "right", open, high, low, close,
                          settle, volume, oi, oi_change, underlying
                   FROM options_eod
                   WHERE symbol=%s AND expiry=%s
                   ORDER BY date, strike, "right" """,
                (symbol, expiry),
            )
        cols = ["date", "strike", "right", "open", "high", "low", "close",
                "settle", "volume", "oi", "oi_change", "underlying"]
        return [dict(zip(cols, r)) for r in rows]

    # ── watchlist snapshot ────────────────────────────────────────────────────

    def ensure_watchlist_state_table(self) -> None:
        self._exec("""
            CREATE TABLE IF NOT EXISTS watchlist_state (
                symbol      TEXT          PRIMARY KEY,
                ltp         NUMERIC(10,2),
                prev_close  NUMERIC(10,2),
                updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
            )
        """)

    def get_latest_ltp(self, symbols: list) -> list:
        """Return the most-recent spot_ticks row for each requested symbol."""
        if not symbols:
            return []
        rows = self._queryall(
            """SELECT DISTINCT ON (symbol) symbol, ltp, ts
               FROM spot_ticks
               WHERE symbol = ANY(%s)
               ORDER BY symbol, ts DESC""",
            [symbols],
        )
        return [{"symbol": r[0], "ltp": float(r[1]), "ts": r[2]} for r in rows]

    def get_watchlist_state(self, symbols: list) -> list:
        """Return persisted ltp + prev_close for watchlist symbols."""
        if not symbols:
            return []
        rows = self._queryall(
            "SELECT symbol, ltp, prev_close, updated_at FROM watchlist_state WHERE symbol = ANY(%s)",
            [symbols],
        )
        return [
            {"symbol": r[0], "ltp": float(r[1]) if r[1] is not None else None,
             "prev_close": float(r[2]) if r[2] is not None else None, "ts": r[3]}
            for r in rows
        ]

    def upsert_watchlist_state(self, rows: list) -> None:
        """Persist ltp + prev_close per symbol (one row per symbol, upserted)."""
        if not rows:
            return
        self.ensure_watchlist_state_table()
        self._execvalues(
            """INSERT INTO watchlist_state (symbol, ltp, prev_close, updated_at)
               VALUES %s
               ON CONFLICT (symbol) DO UPDATE
                 SET ltp=EXCLUDED.ltp,
                     prev_close=COALESCE(EXCLUDED.prev_close, watchlist_state.prev_close),
                     updated_at=EXCLUDED.updated_at""",
            [(r["symbol"], r["ltp"], r.get("prev_close"), r["ts"]) for r in rows],
            template="(%s, %s, %s, %s)",
        )

    def upsert_watchlist_snapshot(self, rows: list) -> None:
        """Persist a manual quote snapshot (symbol, ltp) into spot_ticks."""
        if not rows:
            return
        self._execvalues(
            """INSERT INTO spot_ticks (ts, symbol, ltp, volume)
               VALUES %s ON CONFLICT DO NOTHING""",
            [(r["ts"], r["symbol"], r["ltp"], 0) for r in rows],
            template="(%s, %s, %s, %s)",
        )

    # ── security master ───────────────────────────────────────────────────────

    def ensure_security_master_table(self) -> None:
        self._exec("""
            CREATE TABLE IF NOT EXISTS security_master (
                exchange_code  TEXT        NOT NULL,
                stock_code     TEXT        NOT NULL,
                product_type   TEXT        NOT NULL DEFAULT '',
                expiry_date    TEXT        NOT NULL DEFAULT '',
                strike_price   TEXT        NOT NULL DEFAULT '',
                option_type    TEXT        NOT NULL DEFAULT '',
                stock_name     TEXT,
                series         TEXT,
                isin           TEXT,
                lot_size       TEXT,
                tick_size      TEXT,
                face_value     TEXT,
                updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (exchange_code, stock_code, product_type,
                             expiry_date, strike_price, option_type)
            );
            CREATE INDEX IF NOT EXISTS idx_sec_master_code
                ON security_master (stock_code, exchange_code);
            CREATE INDEX IF NOT EXISTS idx_sec_master_isin
                ON security_master (isin) WHERE isin IS NOT NULL AND isin <> '';
            CREATE INDEX IF NOT EXISTS idx_sec_master_name
                ON security_master (stock_name);
        """)

    def upsert_security_master(self, rows: list) -> None:
        if not rows:
            return
        self.ensure_security_master_table()
        sql = """
            INSERT INTO security_master
                (exchange_code, stock_code, product_type, expiry_date,
                 strike_price, option_type, stock_name, series, isin,
                 lot_size, tick_size, face_value, updated_at)
            VALUES %s
            ON CONFLICT (exchange_code, stock_code, product_type,
                         expiry_date, strike_price, option_type)
            DO UPDATE SET
                stock_name  = EXCLUDED.stock_name,
                series      = EXCLUDED.series,
                isin        = EXCLUDED.isin,
                lot_size    = EXCLUDED.lot_size,
                tick_size   = EXCLUDED.tick_size,
                face_value  = EXCLUDED.face_value,
                updated_at  = EXCLUDED.updated_at
        """
        now = datetime.utcnow()
        data = [
            (
                r["exchange_code"], r["stock_code"],
                r.get("product_type") or "",
                r.get("expiry_date")  or "",
                r.get("strike_price") or "",
                r.get("option_type")  or "",
                r.get("stock_name"),  r.get("series"),
                r.get("isin"),        r.get("lot_size"),
                r.get("tick_size"),   r.get("face_value"),
                now,
            )
            for r in rows
        ]
        self._execvalues(sql, data, template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    def search_security_master(
        self,
        query: str = "",
        exchange: str = "",
        product_type: str = "",
        limit: int = 50,
    ) -> list:
        conditions = []
        params: list = []
        if query:
            conditions.append("(stock_code ILIKE %s OR stock_name ILIKE %s)")
            params += [f"%{query}%", f"%{query}%"]
        if exchange:
            conditions.append("exchange_code = %s")
            params.append(exchange.upper())
        if product_type:
            conditions.append("product_type ILIKE %s")
            params.append(product_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = self._queryall(
            f"""SELECT exchange_code, stock_code, product_type, stock_name,
                       series, isin, expiry_date, strike_price, option_type,
                       lot_size, tick_size
                FROM security_master
                {where}
                ORDER BY exchange_code, stock_code
                LIMIT %s""",
            params,
        )
        cols = ["exchange_code", "stock_code", "product_type", "stock_name",
                "series", "isin", "expiry_date", "strike_price", "option_type",
                "lot_size", "tick_size"]
        return [dict(zip(cols, r)) for r in rows]

    def security_master_stats(self) -> dict:
        rows = self._queryall(
            """SELECT exchange_code, product_type, COUNT(*) AS cnt
               FROM security_master
               GROUP BY exchange_code, product_type
               ORDER BY exchange_code, product_type""",
            [],
        )
        updated = self._queryall(
            "SELECT MAX(updated_at) FROM security_master", []
        )
        last_update = updated[0][0].isoformat() if updated and updated[0][0] else None
        return {
            "last_updated": last_update,
            "breakdown": [
                {"exchange": r[0], "product_type": r[1], "count": r[2]}
                for r in rows
            ],
            "total": sum(r[2] for r in rows),
        }

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._pool.closeall()
        log.info("DataStore connection pool closed.")
