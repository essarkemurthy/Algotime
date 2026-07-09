import logging
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd
import psycopg2
import psycopg2.pool

log = logging.getLogger(__name__)


# ── paper-report row shaping (DB → UI-friendly dicts) ─────────────────────────

def _f(x):
    """Decimal/None → float/None (JSON + arithmetic friendly)."""
    return float(x) if x is not None else None


def _fmt_ts(ts) -> Optional[str]:
    """datetime → 'DD Mon HH:MM' (compact, carries the date for multi-day windows)."""
    return ts.strftime("%d %b %H:%M") if ts is not None else None


def _date_where(col: str, from_date, to_date):
    if from_date and to_date:
        return f"WHERE {col} BETWEEN %s AND %s", (from_date, to_date)
    if from_date:
        return f"WHERE {col} >= %s", (from_date,)
    if to_date:
        return f"WHERE {col} <= %s", (to_date,)
    return "", None


def _paper_trade_dict(d: Dict) -> Dict:
    return {
        "opened_at": _fmt_ts(d["opened_ts"]), "closed_at": _fmt_ts(d["closed_ts"]),
        "trade_date": str(d["trade_date"]), "source": d["source"],
        "strategy": d["strategy"], "product": d["product"], "symbol": d["symbol"],
        "instrument": d["instrument"], "direction": d["direction"],
        "right": (d["right"] or "").strip() or None, "strike": d["strike"],
        "expiry": str(d["expiry"]) if d["expiry"] else None, "qty": d["qty"],
        "entry": _f(d["entry"]), "exit": _f(d["exit"]), "pnl": _f(d["pnl"]),
        "reason": d["reason"],
    }


def _decision_dict(d: Dict) -> Dict:
    return {
        "signal_ts": _fmt_ts(d["signal_ts"]), "received_at": _fmt_ts(d["received_ts"]),
        "strategy": d["strategy"], "symbol": d["symbol"], "direction": d["direction"],
        "trigger_price": _f(d["trigger_price"]), "vwap": _f(d["vwap"]),
        "atr": _f(d["atr"]), "product": d["product"], "decision": d["decision"],
        "reason": d["reason"], "instrument": d["instrument"],
        "entry_price": _f(d["entry_price"]), "entry_time": _fmt_ts(d["entry_ts"]),
        "exec_lag_sec": _f(d["exec_lag_sec"]),
    }


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

    # ── paper trading persistence (testing & monitoring) ──────────────────────

    def ensure_paper_tables(self) -> None:
        """Create the paper-trading tables if missing (idempotent)."""
        self._exec("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id BIGSERIAL PRIMARY KEY, opened_ts TIMESTAMPTZ,
                closed_ts TIMESTAMPTZ NOT NULL, trade_date DATE NOT NULL,
                source TEXT NOT NULL DEFAULT 'Algo', strategy TEXT,
                product TEXT NOT NULL DEFAULT 'cash', symbol TEXT NOT NULL,
                instrument TEXT, direction TEXT, "right" CHAR(2), strike INTEGER,
                expiry DATE, qty INTEGER, entry NUMERIC(14,2), exit NUMERIC(14,2),
                pnl NUMERIC(14,2), reason TEXT);
            CREATE INDEX IF NOT EXISTS idx_paper_trades_date
                ON paper_trades (trade_date DESC, closed_ts DESC);
            CREATE TABLE IF NOT EXISTS paper_signal_decisions (
                id BIGSERIAL PRIMARY KEY, signal_ts TIMESTAMPTZ,
                received_ts TIMESTAMPTZ NOT NULL, trade_date DATE NOT NULL,
                strategy TEXT, symbol TEXT NOT NULL, direction TEXT,
                trigger_price NUMERIC(12,2), vwap NUMERIC(12,2), atr NUMERIC(12,2),
                product TEXT, decision TEXT NOT NULL, reason TEXT, instrument TEXT,
                entry_price NUMERIC(14,2), entry_ts TIMESTAMPTZ, exec_lag_sec NUMERIC(8,1));
            CREATE INDEX IF NOT EXISTS idx_paper_decisions_date
                ON paper_signal_decisions (trade_date DESC, signal_ts DESC);
        """)

    def insert_paper_trade(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO paper_trades
                   (opened_ts, closed_ts, trade_date, source, strategy, product,
                    symbol, instrument, direction, "right", strike, expiry,
                    qty, entry, exit, pnl, reason)
               VALUES
                   (%(opened_ts)s, %(closed_ts)s, %(trade_date)s, %(source)s,
                    %(strategy)s, %(product)s, %(symbol)s, %(instrument)s,
                    %(direction)s, %(right)s, %(strike)s, %(expiry)s, %(qty)s,
                    %(entry)s, %(exit)s, %(pnl)s, %(reason)s)""",
            row,
        )

    def insert_signal_decision(self, row: Dict) -> None:
        self._exec(
            """INSERT INTO paper_signal_decisions
                   (signal_ts, received_ts, trade_date, strategy, symbol, direction,
                    trigger_price, vwap, atr, product, decision, reason, instrument,
                    entry_price, entry_ts, exec_lag_sec)
               VALUES
                   (%(signal_ts)s, %(received_ts)s, %(trade_date)s, %(strategy)s,
                    %(symbol)s, %(direction)s, %(trigger_price)s, %(vwap)s, %(atr)s,
                    %(product)s, %(decision)s, %(reason)s, %(instrument)s,
                    %(entry_price)s, %(entry_ts)s, %(exec_lag_sec)s)""",
            row,
        )

    def get_paper_trades(self, from_date: Optional[date],
                         to_date: Optional[date]) -> List[Dict]:
        where, params = _date_where("trade_date", from_date, to_date)
        rows = self._queryall(
            f"""SELECT opened_ts, closed_ts, trade_date, source, strategy, product,
                       symbol, instrument, direction, "right", strike, expiry,
                       qty, entry, exit, pnl, reason
                FROM paper_trades {where} ORDER BY closed_ts DESC""", params)
        cols = ["opened_ts", "closed_ts", "trade_date", "source", "strategy",
                "product", "symbol", "instrument", "direction", "right", "strike",
                "expiry", "qty", "entry", "exit", "pnl", "reason"]
        return [_paper_trade_dict(dict(zip(cols, r))) for r in rows]

    def get_signal_decisions(self, from_date: Optional[date],
                             to_date: Optional[date]) -> List[Dict]:
        where, params = _date_where("trade_date", from_date, to_date)
        rows = self._queryall(
            f"""SELECT signal_ts, received_ts, strategy, symbol, direction,
                       trigger_price, vwap, atr, product, decision, reason,
                       instrument, entry_price, entry_ts, exec_lag_sec
                FROM paper_signal_decisions {where} ORDER BY signal_ts DESC""", params)
        cols = ["signal_ts", "received_ts", "strategy", "symbol", "direction",
                "trigger_price", "vwap", "atr", "product", "decision", "reason",
                "instrument", "entry_price", "entry_ts", "exec_lag_sec"]
        return [_decision_dict(dict(zip(cols, r))) for r in rows]

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
