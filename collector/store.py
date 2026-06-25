import logging
from datetime import date, datetime
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
        self._execmany(
            """INSERT INTO spot_ticks (ts, symbol, ltp, volume)
               VALUES (%(ts)s, %(symbol)s, %(ltp)s, %(volume)s)
               ON CONFLICT DO NOTHING""",
            rows,
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
        self._execmany(
            """INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
               VALUES (%(ts)s, %(symbol)s, %(interval)s,
                       %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s)
               ON CONFLICT (symbol, "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(candles.high, EXCLUDED.high),
                   low    = LEAST(candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume""",
            rows,
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
        self._execmany(
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
            rows,
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

    # ── intraday signals (VWAP Reversal / ORB alerts) ─────────────────────────

    def insert_signal(self, row: Dict) -> None:
        """Log a detected signal. ON CONFLICT DO NOTHING enforces one signal per
        (trade_date, symbol, strategy, direction) — the dedup guarantee."""
        self._exec(
            """INSERT INTO signals
                   (ts, trade_date, symbol, strategy, direction,
                    trigger_price, vwap, rsi, vol_ratio, atr, notified)
               VALUES
                   (%(ts)s, %(trade_date)s, %(symbol)s, %(strategy)s, %(direction)s,
                    %(trigger_price)s, %(vwap)s, %(rsi)s, %(vol_ratio)s, %(atr)s,
                    %(notified)s)
               ON CONFLICT (trade_date, symbol, strategy, direction) DO NOTHING""",
            row,
        )

    def get_signals(self, trade_date: date) -> List[Dict]:
        rows = self._queryall(
            """SELECT ts, symbol, strategy, direction, trigger_price, vwap,
                      rsi, vol_ratio, atr, notified
               FROM signals WHERE trade_date = %s
               ORDER BY ts DESC""",
            (trade_date,),
        )
        cols = ["ts", "symbol", "strategy", "direction", "trigger_price", "vwap",
                "rsi", "vol_ratio", "atr", "notified"]
        return [dict(zip(cols, r)) for r in rows]

    def get_quote_seed(self, symbols: List[str]) -> Dict[str, Dict]:
        """Last-known price + previous-day close per symbol, for seeding the UI
        when no live broker feed is available.

        last_price = close of the freshest candle (any interval).
        prev_close = the daily close of the prior trading day → used for %-change.
        Returns {symbol: {"last": float, "prev_close": float|None}} for symbols
        that have stored candles; symbols with no data are omitted.
        """
        out: Dict[str, Dict] = {}
        for sym in symbols:
            last = self._queryone(
                "SELECT close FROM candles WHERE symbol=%s ORDER BY ts DESC LIMIT 1",
                (sym,),
            )
            if not last or last[0] is None:
                continue
            daily = self._queryall(
                """SELECT close FROM candles
                   WHERE symbol=%s AND "interval"='1d'
                   ORDER BY ts DESC LIMIT 2""",
                (sym,),
            )
            prev_close = None
            if len(daily) >= 2 and daily[1][0] is not None:
                prev_close = float(daily[1][0])
            elif daily and daily[0][0] is not None:
                prev_close = float(daily[0][0])
            out[sym] = {"last": float(last[0]), "prev_close": prev_close}
        return out

    def insert_options_candles(self, rows: List[Dict]) -> None:
        if not rows:
            return
        self._execmany(
            """INSERT INTO options_candles
                   (ts, symbol, expiry, strike, "right", "interval",
                    open, high, low, close, volume, oi)
               VALUES
                   (%(ts)s, %(symbol)s, %(expiry)s, %(strike)s, %(right)s, %(interval)s,
                    %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(oi)s)
               ON CONFLICT (symbol, expiry, strike, "right", "interval", ts) DO UPDATE
               SET open   = EXCLUDED.open,
                   high   = GREATEST(options_candles.high, EXCLUDED.high),
                   low    = LEAST(options_candles.low,     EXCLUDED.low),
                   close  = EXCLUDED.close,
                   volume = EXCLUDED.volume,
                   oi     = EXCLUDED.oi""",
            rows,
        )

    def get_intraday_bars(self, symbol: str, interval: str,
                          trade_date: date) -> List[Dict]:
        """Fetch a day's candles for a symbol+interval, oldest first — used to
        seed a SymbolSession when the dashboard starts mid-session."""
        rows = self._queryall(
            """SELECT ts, open, high, low, close, volume
               FROM candles
               WHERE symbol = %s AND "interval" = %s AND ts::date = %s
               ORDER BY ts ASC""",
            (symbol, interval, trade_date),
        )
        cols = ["ts", "open", "high", "low", "close", "volume"]
        return [dict(zip(cols, r)) for r in rows]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._pool.closeall()
        log.info("DataStore connection pool closed.")
