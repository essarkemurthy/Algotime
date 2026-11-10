"""Serve the Breeze security master from a local cache when its host stalls.

breeze_connect downloads SecurityMaster.zip (~3 MB) twice: once with urlopen at
import time (an uncaught timeout kills the whole import) and again inside
get_stock_script_list() with urlopen + requests.get (a timeout there is swallowed
and leaves every token dict empty, so WS subscriptions resolve to "4.1!False" and
option feeds never tick). directlink.icicidirect.com black-holes connections
intermittently, so both paths are pointed at data/SecurityMaster.zip, refreshed
from the network when it is older than MAX_AGE and the host answers.

Call install() BEFORE importing breeze_connect. Safe to call repeatedly.
"""
import io
import logging
import os
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "SecurityMaster.zip"
MAX_AGE_SEC = 12 * 3600
DOWNLOAD_TIMEOUT = 25

_orig_urlopen = urllib.request.urlopen
_installed = False


def _is_master(url) -> bool:
    target = url if isinstance(url, str) else getattr(url, "full_url", "")
    return "SecurityMaster.zip" in str(target)


def _cache_fresh() -> bool:
    try:
        return CACHE_PATH.exists() and (time.time() - CACHE_PATH.stat().st_mtime) < MAX_AGE_SEC
    except OSError:
        return False


def refresh(force: bool = False) -> bool:
    """Download the master into the cache. Returns True when the cache is usable."""
    if not force and _cache_fresh():
        return True
    try:
        req = urllib.request.Request(MASTER_URL, headers={"User-Agent": "Mozilla/5.0"})
        with _orig_urlopen(req, timeout=DOWNLOAD_TIMEOUT) as r:
            data = r.read()
        if not data.startswith(b"PK"):
            raise ValueError("response is not a zip archive")
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".zip.part")
        tmp.write_bytes(data)
        os.replace(tmp, CACHE_PATH)
        log.info("Security master refreshed (%d bytes).", len(data))
        return True
    except Exception as exc:
        if CACHE_PATH.exists():
            age_h = (time.time() - CACHE_PATH.stat().st_mtime) / 3600
            log.warning("Security master download failed (%s); using cached copy %.1f h old.", exc, age_h)
            return True
        log.warning("Security master download failed and no cache exists: %s", exc)
        return False


def _urlopen(url, *args, **kwargs):
    if _is_master(url) and CACHE_PATH.exists():
        return io.BytesIO(CACHE_PATH.read_bytes())
    return _orig_urlopen(url, *args, **kwargs)


class _CachedResponse:
    """Just enough of requests.Response for the SDK's raise_for_status()/content."""
    status_code = 200
    ok = True

    def __init__(self, data: bytes) -> None:
        self.content = data

    def raise_for_status(self) -> None:
        return None


def install() -> None:
    """Patch urlopen (import-time fetch) and requests.get (SDK's second fetch)."""
    global _installed
    refresh()
    if _installed:
        return
    urllib.request.urlopen = _urlopen
    try:
        import requests
        _orig_get = requests.get

        def _get(url, *args, **kwargs):
            if _is_master(url) and CACHE_PATH.exists():
                return _CachedResponse(CACHE_PATH.read_bytes())
            return _orig_get(url, *args, **kwargs)
        requests.get = _get
    except Exception as exc:          # requests missing is the SDK's problem, not ours
        log.debug("requests patch skipped: %s", exc)
    _installed = True
    # If the SDK module is already imported it bound the original urlopen name.
    try:
        import sys
        mod = sys.modules.get("breeze_connect.breeze_connect")
        if mod is not None:
            mod.urlopen = _urlopen
    except Exception:
        pass
