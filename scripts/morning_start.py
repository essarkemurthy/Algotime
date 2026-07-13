#!/usr/bin/env python3
"""
scripts/morning_start.py — daily one-command bootstrap for algo paper trading.

Run this each trading morning (before 09:15) AFTER pasting the day's fresh Breeze
session token into .env. It:
  1. reads BREEZE_SESSION_TOKEN from .env,
  2. validates it against the running app (/api/setup/broker/test),
  3. saves + reconnects the live feed (/api/setup/broker/save) — no app restart,
  4. launches the intraday algo engine (and options if --options),
  5. prints the connection + algo status.

Keep app.py running continuously (its import is slow); this only reconnects the
token and arms the engine on the already-running process.

Usage:
  python scripts/morning_start.py                 # intraday cash engine
  python scripts/morning_start.py --options       # also arm options engine
  python scripts/morning_start.py --host http://127.0.0.1:8000
"""
import os, sys, json, argparse, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def _post(host, path, body):
    req = urllib.request.Request(host + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()}
    except Exception as e:
        return None, {"error": str(e)}


def _get(host, path):
    try:
        with urllib.request.urlopen(host + path, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        return {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--options", action="store_true", help="also arm the options algo engine")
    args = ap.parse_args()
    host = args.host.rstrip("/")

    key    = os.environ.get("BREEZE_API_KEY", "")
    secret = os.environ.get("BREEZE_API_SECRET", "")
    token  = os.environ.get("BREEZE_SESSION_TOKEN", "")
    if not all([key, secret, token]):
        print("ERROR: BREEZE_API_KEY / API_SECRET / SESSION_TOKEN missing in .env")
        sys.exit(1)
    creds = {"type": "icici", "api_key": key, "api_secret": secret, "session_token": token}

    # 0. app reachable?
    st = _get(host, "/api/status")
    if "error" in st:
        print(f"ERROR: app not reachable at {host} — start app.py first. ({st['error']})")
        sys.exit(1)

    # 1. validate token
    code, res = _post(host, "/api/setup/broker/test", creds)
    if not (code == 200 and res.get("ok")):
        print(f"ERROR: Breeze token invalid/expired: {res.get('error') or res}")
        print("  → Log in at the Breeze API portal, paste today's session token into .env, and re-run.")
        sys.exit(2)
    print(f"Token OK — {res.get('name')}")

    # 2. save + reconnect the live feed
    code, res = _post(host, "/api/setup/broker/save", creds)
    if not (code == 200 and res.get("connected")):
        print(f"ERROR: connect failed: {res}")
        sys.exit(3)
    print("Broker connected + feeds resubscribed.")

    # 3. arm the algo engine(s)
    cfg = {"trade_intraday": True}
    if args.options:
        cfg["trade_options"] = True
    code, snap = _post(host, "/api/algo/paper/config", cfg)
    c = snap.get("config", {})
    print(f"Algo engines — intraday: {c.get('trade_intraday')}  options: {c.get('trade_options')}")
    print(f"Enabled strategies: {[s['strategy'] for s in snap.get('strategies', []) if s.get('enabled')]}")
    print("Ready. The algo will trade enabled signals in the entry window and square off at 15:15.")


if __name__ == "__main__":
    main()
