"""
collector/security_master.py

Downloads the ICICI Direct / Breeze security master ZIP, parses it, and
upserts every row into the `security_master` PostgreSQL table.

Source (no auth required):
  https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip

Scheduled daily at 08:30 IST (03:00 UTC) — before NSE market open.

CLI usage:
  python -m collector.security_master

API usage (from app.py):
  from collector.security_master import SecurityMasterDownloader
  SecurityMasterDownloader(db_url, progress_cb=print).run()
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from typing import Callable, List, Optional

import requests

try:
    from .store import DataStore
except ImportError:
    from collector.store import DataStore  # standalone / CLI

log = logging.getLogger(__name__)

_URL = "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"
_TIMEOUT = 60  # seconds

# ── Column-name aliases ───────────────────────────────────────────────────────
# The CSV header varies across versions of the file; normalise to canonical names.
_ALIASES: dict[str, str] = {
    "exchangecode":   "exchange_code",
    "exchange_code":  "exchange_code",
    "exchange":       "exchange_code",
    "stockcode":      "stock_code",
    "stock_code":     "stock_code",
    "shortname":      "stock_code",
    "short_name":     "stock_code",
    "scripcode":      "stock_code",
    "producttype":    "product_type",
    "product_type":   "product_type",
    "series":         "series",
    "seriesname":     "series",
    "series_name":    "series",
    "stockname":      "stock_name",
    "stock_name":     "stock_name",
    "companyname":    "stock_name",
    "company_name":   "stock_name",
    "scripname":      "stock_name",
    "scrip_name":     "stock_name",
    "isin":           "isin",
    "isincode":       "isin",
    "expirydate":     "expiry_date",
    "expiry_date":    "expiry_date",
    "strikeprice":    "strike_price",
    "strike_price":   "strike_price",
    "optiontype":     "option_type",
    "option_type":    "option_type",
    "right":          "option_type",
    "lotsize":        "lot_size",
    "lot_size":       "lot_size",
    "lotsz":          "lot_size",
    "ticksize":       "tick_size",
    "tick_size":      "tick_size",
    "facevalue":      "face_value",
    "face_value":     "face_value",
    "faceval":        "face_value",
}


def _normalise_header(raw: str) -> str:
    return _ALIASES.get(raw.strip().lower().replace(" ", "").replace("_", ""), raw.strip().lower())


def _safe(val: str) -> str:
    return (val or "").strip()


def _parse_rows(text: str) -> List[dict]:
    """Parse the CSV text and return a list of normalised row dicts."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Security master CSV has no headers.")

    # Build header map
    col_map = {f: _normalise_header(f) for f in reader.fieldnames}
    log.debug("Security master columns: %s", list(col_map.values()))

    rows: List[dict] = []
    for raw in reader:
        r = {col_map[k]: _safe(v) for k, v in raw.items()}

        # Require at minimum exchange + stock_code
        if not r.get("exchange_code") or not r.get("stock_code"):
            continue

        rows.append({
            "exchange_code": r.get("exchange_code", ""),
            "stock_code":    r.get("stock_code", ""),
            "product_type":  r.get("product_type", ""),
            "stock_name":    r.get("stock_name", "") or None,
            "series":        r.get("series", "") or None,
            "isin":          r.get("isin", "") or None,
            "expiry_date":   r.get("expiry_date", ""),
            "strike_price":  r.get("strike_price", ""),
            "option_type":   r.get("option_type", ""),
            "lot_size":      r.get("lot_size", "") or None,
            "tick_size":     r.get("tick_size", "") or None,
            "face_value":    r.get("face_value", "") or None,
        })

    return rows


class SecurityMasterDownloader:
    def __init__(self, db_url: str, progress_cb: Optional[Callable[[str], None]] = None) -> None:
        self._store = DataStore(db_url)
        self._cb = progress_cb or (lambda msg: log.info(msg))

    def run(self) -> int:
        """Download, parse, upsert. Returns number of rows upserted."""
        self._cb("Security master: downloading…")
        try:
            resp = requests.get(_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            self._cb(f"Security master: download failed — {exc}")
            raise

        self._cb(f"Security master: downloaded {len(resp.content):,} bytes, extracting…")

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # Find the CSV inside — typically the only file or named SecurityMaster.csv
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise ValueError("No CSV found inside SecurityMaster.zip")
            csv_name = csv_names[0]
            self._cb(f"Security master: parsing {csv_name}…")
            text = zf.read(csv_name).decode("utf-8", errors="replace")

        rows = _parse_rows(text)
        self._cb(f"Security master: {len(rows):,} instruments parsed, upserting to DB…")

        self._store.upsert_security_master(rows)
        self._cb(f"Security master: done — {len(rows):,} rows upserted at {datetime.now().strftime('%H:%M:%S')}")
        return len(rows)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_url = os.environ.get("DB_URL")
    if not db_url:
        print("ERROR: DB_URL not set.")
        sys.exit(1)

    n = SecurityMasterDownloader(db_url, progress_cb=print).run()
    print(f"Done — {n:,} rows.")
