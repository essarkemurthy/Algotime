"""
signals/notifier.py — formats and dispatches signal notifications.

Channels are decoupled from any web framework: the in-app channel is a plain
callable injected by the host (app.py wires it to its WebSocket broadcast).
Telegram / generic-webhook channels use only the standard library (urllib), so
no new dependency is introduced; both are opt-in via config flags.

Notification policy (the engine handles DB/file logging separately):
  • kill-switch off (cfg.enabled = False) → dispatch() sends nothing.
  • dry-run (cfg.dry_run = True)          → print the formatted line to the log,
                                            send to no live channel.
"""

import json
import logging
import urllib.request
from typing import Callable, Optional

from .config import SignalConfig
from .detectors import Signal

log = logging.getLogger("signals")


def format_message(sig: Signal) -> str:
    """Human-readable one-liner, per the spec's required field order."""
    rsi = "n/a" if sig.rsi != sig.rsi else f"{sig.rsi:.1f}"   # NaN check
    return (
        f"{sig.symbol} | {sig.strategy} | {sig.direction} | "
        f"trig {sig.trigger_price:.2f} | VWAP {sig.vwap:.2f} | "
        f"RSI {rsi} | vol x{sig.vol_ratio:.2f} | "
        f"{sig.ts.strftime('%Y-%m-%d %H:%M')} IST"
    )


def to_payload(sig: Signal) -> dict:
    """Structured payload for the in-app WS toast and webhook channels."""
    return {
        "type":          "signal",
        "symbol":        sig.symbol,
        "strategy":      sig.strategy,
        "direction":     sig.direction,
        "trigger_price": round(sig.trigger_price, 2),
        "vwap":          round(sig.vwap, 2),
        "rsi":           None if sig.rsi != sig.rsi else round(sig.rsi, 1),
        "vol_ratio":     round(sig.vol_ratio, 2),
        "ts":            sig.ts.strftime("%Y-%m-%d %H:%M:%S"),
        "message":       format_message(sig),
    }


class NotificationDispatcher:
    def __init__(self, cfg: SignalConfig,
                 broadcast_fn: Optional[Callable[[dict], None]] = None) -> None:
        self.cfg = cfg
        self._broadcast_fn = broadcast_fn   # callable(payload_dict) → schedules WS broadcast

    def dispatch(self, sig: Signal) -> bool:
        """Send the signal to all enabled channels. Returns True if anything sent."""
        if not self.cfg.enabled:
            return False

        msg = format_message(sig)
        if self.cfg.dry_run:
            log.info("[DRY-RUN] would notify: %s", msg)
            return False

        sent = False
        if self.cfg.notify_in_app and self._broadcast_fn is not None:
            try:
                self._broadcast_fn(to_payload(sig))
                sent = True
            except Exception as exc:
                log.warning("In-app notify failed: %s", exc)

        if self.cfg.notify_telegram:
            sent = self._send_telegram(msg) or sent

        if self.cfg.notify_webhook:
            sent = self._send_webhook(to_payload(sig)) or sent

        return sent

    # ── optional channels (stdlib only) ───────────────────────────────────────

    def _send_telegram(self, text: str) -> bool:
        if not (self.cfg.telegram_bot_token and self.cfg.telegram_chat_id):
            log.warning("Telegram enabled but token/chat_id missing.")
            return False
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
        data = json.dumps({"chat_id": self.cfg.telegram_chat_id, "text": text}).encode()
        return self._post(url, data)

    def _send_webhook(self, payload: dict) -> bool:
        if not self.cfg.webhook_url:
            log.warning("Webhook enabled but SIGNAL_WEBHOOK_URL missing.")
            return False
        return self._post(self.cfg.webhook_url, json.dumps(payload).encode())

    @staticmethod
    def _post(url: str, data: bytes) -> bool:
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception as exc:
            log.warning("POST to %s failed: %s", url.split("?")[0], exc)
            return False
