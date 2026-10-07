#!/usr/bin/env python3
"""Build the 15m candle series by resampling 5m bars.

Breeze has no 15-minute interval - the SDK accepts only 1minute, 5minute,
30minute and 1day - so 15m can never be downloaded. The rows that existed came
from the app's live tick aggregation, which only covers days the dashboard
happened to be running, leaving the series almost empty and months stale.

Deriving it from the stored 5m series costs no API calls and is exact: open is
the first 5m open, close the last close, high/low the extremes, volume the sum.

Buckets are anchored to 09:15 IST so a bucket holds a real session's
09:15/09:20/09:25 triple rather than straddling the open. Pre-open auction
prints fall into their own earlier bucket, which is correct.

Idempotent - safe to re-run; existing rows are overwritten with the derived
values.

    python scripts/derive_15m.py
    python scripts/derive_15m.py --days 7     # only recent sessions
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

SQL = """
INSERT INTO candles (ts, symbol, "interval", open, high, low, close, volume)
SELECT b, symbol, '15m',
       (array_agg(open  ORDER BY ts ASC ))[1],
       MAX(high), MIN(low),
       (array_agg(close ORDER BY ts DESC))[1],
       SUM(volume)
FROM (
  SELECT date_bin('15 minutes', ts,
                  TIMESTAMPTZ '2000-01-03 09:15:00+05:30') AS b,
         ts, symbol, open, high, low, close, volume
  FROM candles
  WHERE "interval" = '5m' {window}
) t
GROUP BY b, symbol
ON CONFLICT (symbol, "interval", ts) DO UPDATE
  SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
      close = EXCLUDED.close, volume = EXCLUDED.volume;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0,
                    help="only resample the last N days (0 = whole history)")
    args = ap.parse_args()

    db_url = os.getenv("DB_URL", "")
    if not db_url:
        print("DB_URL not set - nothing to do.")
        return 0

    window = ""
    params = ()
    if args.days > 0:
        window = "AND ts >= NOW() - (%s || ' days')::interval"
        params = (str(args.days),)

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM candles WHERE "interval"=%s', ("15m",))
            before = cur.fetchone()[0]
            cur.execute(SQL.format(window=window), params)
            conn.commit()
            cur.execute('SELECT COUNT(*) FROM candles WHERE "interval"=%s', ("15m",))
            after = cur.fetchone()[0]
        print(f"15m rows: {before:,} -> {after:,}  (+{after - before:,})")
    except Exception as exc:
        conn.rollback()
        print(f"derive_15m failed: {exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
