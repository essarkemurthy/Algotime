#!/usr/bin/env python3
"""Derive 5m / 15m / 30m candles from the stored 1m series (no API calls).

Used by the dashboard's intraday sync: it pulls 1m bars from Breeze every few
minutes and this builds the higher intervals so charts, backtests and the
signal engine see a current series all day. Only buckets that have fully
elapsed are written, so an in-progress bar is never stored half-formed.

Buckets are anchored to 09:15 IST (a 15m bucket holds 09:15/09:20/09:25).
Idempotent: existing rows are overwritten with the derived values; the
end-of-day Breeze fill then overwrites 5m/30m with the exchange's own bars.

    python scripts/derive_bars.py --days 1
    python scripts/derive_bars.py --days 7 --intervals 5m,30m
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import psycopg2

MINUTES = {"5m": 5, "15m": 15, "30m": 30}

SQL = """
INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
SELECT b, symbol, %(iv)s,
       (array_agg(open  ORDER BY ts ASC ))[1],
       MAX(high), MIN(low),
       (array_agg(close ORDER BY ts DESC))[1],
       SUM(volume)
FROM (
  SELECT date_bin((%(mins)s || ' minutes')::interval, ts,
                  TIMESTAMPTZ '2000-01-03 09:15:00+05:30') AS b,
         ts, symbol, open, high, low, close, volume
  FROM candles
  WHERE "interval" = '1m'
    AND ts >= NOW() - (%(days)s || ' days')::interval
) t
GROUP BY b, symbol
HAVING b + (%(mins)s || ' minutes')::interval <= NOW()
ON CONFLICT (symbol, "interval", ts) DO UPDATE
  SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
      close = EXCLUDED.close, volume = EXCLUDED.volume;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="resample the last N days (default 1)")
    ap.add_argument("--intervals", default="5m,15m,30m",
                    help="comma list of target intervals (default 5m,15m,30m)")
    args = ap.parse_args()
    ivs = [x.strip() for x in args.intervals.split(",") if x.strip()]
    bad = [x for x in ivs if x not in MINUTES]
    if bad:
        print(f"unsupported interval(s): {bad}; choose from {sorted(MINUTES)}")
        return 2

    db_url = os.getenv("DB_URL", "")
    if not db_url:
        print("DB_URL not set - nothing to do.")
        return 0

    conn = psycopg2.connect(db_url)
    try:
        out = []
        with conn.cursor() as cur:
            for iv in ivs:
                cur.execute(SQL, {"iv": iv, "mins": str(MINUTES[iv]), "days": str(args.days)})
                out.append(f"{iv}={cur.rowcount}")
        conn.commit()
        print("derived rows (upserted): " + "  ".join(out))
    except Exception as exc:
        conn.rollback()
        print(f"derive_bars failed: {exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
