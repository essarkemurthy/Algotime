#!/usr/bin/env python3
"""Launch-time credential check.

Breeze session tokens expire every 24 h, so the usual failure mode is that the
app starts, reports connected=false, and sits there dead with no explanation.
This runs *before* the app: it validates the saved token against the broker and,
only if that fails, prompts for a fresh one.

Credentials are read from .env first, falling back to data/setup.json per field,
so whatever is already saved is reused and the prompt only asks for what is
actually missing or expired. A token accepted here is written back to BOTH
stores, keeping them from drifting apart.

    python scripts/preflight_token.py           # prompt if needed
    python scripts/preflight_token.py --check   # never prompt; exit 1 if invalid

Exit 0 = credentials good, safe to launch.  Exit 1 = not usable.
"""
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ENV_FILE   = ROOT / ".env"
SETUP_FILE = ROOT / "data" / "setup.json"
LOGIN_URL  = "https://api.icicidirect.com/apiuser/home"
FIELDS     = ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN")
SETUP_KEYS = {"BREEZE_API_KEY": "api_key",
              "BREEZE_API_SECRET": "api_secret",
              "BREEZE_SESSION_TOKEN": "session_token"}


def _say(msg=""):
    print(msg, flush=True)


def _read_env() -> dict:
    out = {}
    if not ENV_FILE.exists():
        return out
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _read_setup() -> dict:
    if not SETUP_FILE.exists():
        return {}
    try:
        return json.loads(SETUP_FILE.read_text(encoding="utf-8")).get("broker", {})
    except Exception:
        return {}


def _load_credentials() -> dict:
    """.env wins per field; data/setup.json fills any blank."""
    env, saved = _read_env(), _read_setup()
    creds = {}
    for f in FIELDS:
        creds[f] = env.get(f) or saved.get(SETUP_KEYS[f], "") or ""
    return creds


def _write_env(updates: dict) -> None:
    """Rewrite only the touched keys, preserving comments and every other line."""
    lines = (ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
             if ENV_FILE.exists() else [])
    seen = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k in updates:
            lines[i] = f"{k}={updates[k]}"
            seen.add(k)
    for k, v in updates.items():
        if k not in seen:
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_setup(updates: dict) -> None:
    cfg = {}
    if SETUP_FILE.exists():
        try:
            cfg = json.loads(SETUP_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    broker = cfg.setdefault("broker", {})
    broker.setdefault("type", "icici")
    for k, v in updates.items():
        broker[SETUP_KEYS[k]] = v
    if broker.get("api_key") and broker.get("session_token"):
        cfg["setup_complete"] = True
    SETUP_FILE.parent.mkdir(exist_ok=True)
    SETUP_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _validate(api_key: str, api_secret: str, token: str):
    """(ok, detail). detail is the account name on success, else the error."""
    if not (api_key and api_secret and token):
        return False, "missing api_key / api_secret / session_token"
    try:
        from breeze_connect import BreezeConnect
        api = BreezeConnect(api_key=api_key)
        api.generate_session(api_secret=api_secret, session_token=token)
        resp = api.get_customer_details(api_session=token)
        if resp and resp.get("Status") == 200:
            return True, (resp.get("Success") or {}).get("idirect_user_name", "verified")
        return False, str((resp or {}).get("Error") or "authentication rejected")
    except Exception as exc:
        return False, str(exc)


def _check_subscription(api_key: str, api_secret: str, token: str):
    """(ok, detail) — is the market-data subscription actually live?

    Breeze exposes no subscription-status endpoint, so the only real test is to
    ask for a quote: authentication can succeed while the data entitlement is
    inactive, which shows up as an empty/failed quote rather than an auth error.
    """
    try:
        from breeze_connect import BreezeConnect
        api = BreezeConnect(api_key=api_key)
        api.generate_session(api_secret=api_secret, session_token=token)
        resp = api.get_quotes(stock_code="NIFTY", exchange_code="NSE",
                              product_type="cash", expiry_date="", right="",
                              strike_price="")
        if not resp:
            return False, "no response to get_quotes"
        if resp.get("Status") != 200:
            return False, str(resp.get("Error") or f"status {resp.get('Status')}")
        rows = resp.get("Success") or []
        if not rows:
            return False, "quote returned no rows — data subscription may be inactive"
        ltp = (rows[0] or {}).get("ltp")
        return True, f"NIFTY quote OK (ltp={ltp})"
    except Exception as exc:
        return False, str(exc)


def _prompt(label: str, secret_hint: str = "") -> str:
    suffix = f" [saved: …{secret_hint[-4:]}]" if secret_hint else ""
    try:
        return input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def main() -> int:
    check_only = "--check" in sys.argv
    creds = _load_credentials()

    _say()
    _say("  Checking broker credentials…")
    ok, detail = _validate(creds["BREEZE_API_KEY"], creds["BREEZE_API_SECRET"],
                           creds["BREEZE_SESSION_TOKEN"])
    if ok:
        _say(f"  Session is active — {detail}")
        sub_ok, sub_detail = _check_subscription(
            creds["BREEZE_API_KEY"], creds["BREEZE_API_SECRET"],
            creds["BREEZE_SESSION_TOKEN"])
        if sub_ok:
            _say(f"  Market-data subscription live — {sub_detail}")
        else:
            # Not fatal: auth works, so the app can still start and the REST
            # paths function. Surfaced because it silently starves the feed.
            _say(f"  WARNING market data looks inactive — {sub_detail}")
            _say("           Check your Breeze plan at api.icicidirect.com.")
        _say()
        return 0

    _say(f"  Session not usable: {detail}")
    if check_only:
        return 1

    # Anything already saved is reused; only blanks are asked for.
    for field in ("BREEZE_API_KEY", "BREEZE_API_SECRET"):
        if not creds[field]:
            _say()
            _say(f"  {field} is not saved anywhere.")
            creds[field] = _prompt(field)

    _say()
    _say("  " + "=" * 58)
    _say("   A fresh session token is needed (they expire every 24 hours).")
    _say(f"   API key in use: …{creds['BREEZE_API_KEY'][-6:]}")
    _say("   1. Log in at " + LOGIN_URL)
    _say("   2. Copy the 'apisession' value")
    _say("  " + "=" * 58)
    try:
        webbrowser.open(LOGIN_URL)
    except Exception:
        pass

    for attempt in range(1, 4):
        _say()
        token = _prompt("Paste session token (blank to skip)",
                        creds["BREEZE_SESSION_TOKEN"])
        if not token:
            _say("  Skipped — the app will start but stay disconnected.")
            return 1
        _say("  Validating…")
        ok, detail = _validate(creds["BREEZE_API_KEY"], creds["BREEZE_API_SECRET"], token)
        if ok:
            creds["BREEZE_SESSION_TOKEN"] = token
            try:
                _write_env(creds)
                _write_setup(creds)
                _say(f"  Accepted — {detail}. Saved to .env and data/setup.json.")
            except Exception as exc:
                _say(f"  Accepted, but saving failed: {exc}")
            _say()
            return 0
        _say(f"  Rejected: {detail}  (attempt {attempt}/3)")

    _say()
    _say("  Could not validate a token. Starting anyway — the app will be offline.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
