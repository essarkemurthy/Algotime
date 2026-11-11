"""
scripts/fetch_nifty_history.py — NIFTY 50 1-minute history into PostgreSQL `nifty_1m`.

Source: Breeze get_historical_data_v2 (interval "1minute", NIFTY/NSE/cash), which
serves 1-minute index bars back to at least 2022-01-03 (verified). One request
returns at most 1000 rows, so sessions are fetched two at a time (<= 752 rows).

Resumable: the trading calendar is the NIFTY daily series already in `candles`;
every session that is absent from nifty_1m (or has < MIN_BARS bars) is fetched,
so re-running only pulls what is missing. Existing NIFTY 1m rows in `candles`
seed the table first (no API calls for them).

    python scripts/fetch_nifty_history.py                 # 2022-01-01 → today
    python scripts/fetch_nifty_history.py --from 2023-01-01 --to 2023-12-31
    python scripts/fetch_nifty_history.py --report-only   # coverage / gap report

Timestamps are stored as IST (+05:30) bar-open times, as Breeze reports them.
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv                      # noqa: E402
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("fetch_nifty")
IST = timezone(timedelta(hours=5, minutes=30))
MIN_BARS = 70            # sessions below this are special/partial (spec: excluded)
FULL_BARS = 375          # 09:15 .. 15:29
CALLS_PER_MINUTE = 100
MAX_ATTEMPTS = 4
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"

_last_call = 0.0
_calls = 0


def _rate_limited(fn, *args, **kwargs):
    global _last_call, _calls
    wait = (60.0 / CALLS_PER_MINUTE) - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    _calls += 1
    return fn(*args, **kwargs)


def _breeze_dt(d: date, hh: int, mm: int) -> str:
    return f"{d.isoformat()}T{hh:02d}:{mm:02d}:00.000Z"


def _parse_dt(raw) -> Optional[datetime]:
    s = str(raw or "")[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


# ── DB ────────────────────────────────────────────────────────────────────────

def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nifty_1m (
                ts     TIMESTAMPTZ PRIMARY KEY,
                open   NUMERIC NOT NULL,
                high   NUMERIC NOT NULL,
                low    NUMERIC NOT NULL,
                close  NUMERIC NOT NULL,
                volume BIGINT  NOT NULL DEFAULT 0
            )""")
    conn.commit()


def seed_from_candles(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO nifty_1m (ts, open, high, low, close, volume)
            SELECT ts, open, high, low, close, COALESCE(volume, 0)
              FROM candles WHERE symbol = 'NIFTY' AND "interval" = '1m'
            ON CONFLICT (ts) DO NOTHING""")
        n = cur.rowcount
    conn.commit()
    return n


def trading_days(conn, d0: date, d1: date) -> List[date]:
    """NSE sessions = dates with a NIFTY daily bar in `candles` (2012 →)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d
              FROM candles WHERE symbol = 'NIFTY' AND "interval" = '1d'
               AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s
             ORDER BY 1""", (d0, d1))
        return [r[0] for r in cur.fetchall()]


def bars_per_session(conn, d0: date, d1: date) -> Dict[date, int]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d, count(*)
              FROM nifty_1m
             WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s
             GROUP BY 1""", (d0, d1))
        return {r[0]: int(r[1]) for r in cur.fetchall()}


def upsert(conn, rows: List[Tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO nifty_1m (ts, open, high, low, close, volume) VALUES %s
            ON CONFLICT (ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high,
                low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume""",
            rows, page_size=1000)
        n = cur.rowcount
    conn.commit()
    return n


# ── Breeze ────────────────────────────────────────────────────────────────────

def connect_breeze():
    from breeze_connect import BreezeConnect
    api = BreezeConnect(api_key=os.environ["BREEZE_API_KEY"])
    api.generate_session(api_secret=os.environ["BREEZE_API_SECRET"],
                         session_token=os.environ["BREEZE_SESSION_TOKEN"])
    return api


def fetch_days(api, d0: date, d1: date) -> Optional[List[Tuple]]:
    """All 1-minute bars from d0 09:15 to d1 15:30 (inclusive dates). None = failed."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _rate_limited(
                api.get_historical_data_v2, interval="1minute",
                from_date=_breeze_dt(d0, 9, 15), to_date=_breeze_dt(d1, 15, 30),
                stock_code="NIFTY", exchange_code="NSE", product_type="cash",
                expiry_date="", right="", strike_price="")
        except Exception as exc:
            log.warning("fetch %s..%s attempt %d/%d: %s", d0, d1, attempt, MAX_ATTEMPTS, exc)
            time.sleep(2 * attempt)
            continue
        if resp.get("Status") != 200:
            log.warning("fetch %s..%s non-200: %s", d0, d1, resp.get("Error"))
            time.sleep(2 * attempt)
            continue
        rows = []
        for raw in resp.get("Success") or []:
            ts = _parse_dt(raw.get("datetime"))
            if ts is None:
                continue
            try:
                rows.append((ts, float(raw["open"]), float(raw["high"]), float(raw["low"]),
                             float(raw["close"]), int(float(raw.get("volume") or 0))))
            except (KeyError, TypeError, ValueError):
                continue
        return rows
    return None


# ── Coverage report ───────────────────────────────────────────────────────────

def coverage_report(conn, d0: date, d1: date, write: bool = True) -> dict:
    sessions = trading_days(conn, d0, d1)
    have = bars_per_session(conn, d0, d1)
    missing = [d for d in sessions if d not in have]
    special = [(d, have[d]) for d in sessions if d in have and have[d] < MIN_BARS]
    partial = [(d, have[d]) for d in sessions if d in have and MIN_BARS <= have[d] < FULL_BARS - 5]
    extra = sorted(d for d in have if d not in set(sessions))
    # intra-session minute gaps on normal sessions (bars absent between first and last)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT d, (EXTRACT(EPOCH FROM (max(ts) - min(ts))) / 60 + 1) - count(*) AS holes
              FROM (SELECT ts, (ts AT TIME ZONE 'Asia/Kolkata')::date AS d FROM nifty_1m
                     WHERE (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %s AND %s) x
             GROUP BY d HAVING (EXTRACT(EPOCH FROM (max(ts) - min(ts))) / 60 + 1) - count(*) > 0
             ORDER BY holes DESC""", (d0, d1))
        holes = [(r[0], int(r[1])) for r in cur.fetchall()]
    rep = {"from": d0, "to": d1, "sessions": len(sessions), "present": len(sessions) - len(missing),
           "missing": missing, "special": special, "partial": partial, "extra": extra,
           "holes": holes, "api_calls": _calls}
    lines = [f"# nifty_1m coverage  {d0} -> {d1}", "",
             f"- NSE sessions (from NIFTY daily series): **{len(sessions)}**",
             f"- sessions with 1-minute bars: **{rep['present']}**",
             f"- missing sessions: **{len(missing)}**" + (f"  {missing[:20]}" if missing else ""),
             f"- special/partial sessions (< {MIN_BARS} bars, excluded by the strategy): **{len(special)}**"
             + (f"  {special[:20]}" if special else ""),
             f"- short sessions ({MIN_BARS}..{FULL_BARS - 6} bars): **{len(partial)}**"
             + (f"  {partial[:20]}" if partial else ""),
             f"- dates in nifty_1m with no daily bar (special sessions outside the daily series): "
             f"**{len(extra)}**" + (f"  {extra[:20]}" if extra else ""),
             f"- sessions with missing minutes inside the day: **{len(holes)}**"
             + (f"  worst {holes[:10]}" if holes else ""),
             f"- Breeze calls this run: {_calls}", ""]
    text = "\n".join(lines)
    print(text)
    if write:
        REPORT_DIR.mkdir(exist_ok=True)
        (REPORT_DIR / "nifty_1m_coverage.md").write_text(text, encoding="utf-8")
    return rep


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="d0", default="2022-01-01")
    ap.add_argument("--to", dest="d1", default=date.today().isoformat())
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--no-seed", action="store_true", help="skip seeding from candles")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):          # Windows console defaults to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)

    conn = psycopg2.connect(os.environ["DB_URL"])
    ensure_table(conn)
    if args.report_only:
        coverage_report(conn, d0, d1)
        return 0
    if not args.no_seed:
        log.info("seeded %d rows from candles(NIFTY,1m)", seed_from_candles(conn))

    sessions = trading_days(conn, d0, d1)
    have = bars_per_session(conn, d0, d1)
    # (re)fetch anything short of a full session: partial rows seeded from `candles`
    # (e.g. 238-bar days from the old collector) are overwritten by the upsert
    todo = [d for d in sessions if have.get(d, 0) < FULL_BARS - 5 and d <= date.today()]
    log.info("%d sessions in range, %d to fetch", len(sessions), len(todo))
    if todo:
        api = connect_breeze()
        # pair consecutive sessions: two full days = 750 rows < Breeze's 1000-row cap
        i, failed, inserted = 0, [], 0
        while i < len(todo):
            a = todo[i]
            b = todo[i + 1] if i + 1 < len(todo) and (todo[i + 1] - a).days <= 3 else a
            rows = fetch_days(api, a, b)
            if rows is None:
                failed.append((a, b))
            else:
                inserted += upsert(conn, rows)
                got = sorted({r[0].date() for r in rows})
                log.info("%s..%s  rows=%d  days=%s  (calls=%d)", a, b, len(rows),
                         ",".join(d.isoformat() for d in got), _calls)
            i += 2 if b != a else 1
        log.info("inserted/updated %d rows; %d chunk(s) failed %s", inserted, len(failed), failed[:10])
    coverage_report(conn, d0, d1)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
