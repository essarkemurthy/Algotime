"""
feed_guard.py — keep the live price cache honest.

Two defences for the Breeze tick stream, both pure and unit-tested:

1. Derivative ticks must never be learned as an index or equity. Breeze stamps
   an option contract's ticks with the *underlying's* display name ("NIFTY 50"),
   so after a reconnect (which clears the token map) a still-streaming contract
   from an earlier day looked like the index and its premium (~170) was written
   into the NIFTY tile — the "odd numbers / flicker" seen on 2026-11-19.
   `is_derivative_tick` recognises such ticks; `option_key_from_tick` rebuilds
   the app's option key so a known contract can be re-mapped instead.

2. A plausibility guard on every non-option price: a single tick more than
   `max_jump` away from the last accepted price is held back. Indices and
   equities do not move 15% between two ticks; if the feed really has re-based
   (a genuine gap or a corrected quote), `confirm_after` consecutive agreeing
   outliers are accepted and the baseline moves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, Optional, Tuple

_DERIV_EXCHANGE_WORDS = ("futures", "options", "f&o", "nfo", "bfo", "derivative")
_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%d-%m-%Y", "%d%b%Y")


def _s(v) -> str:
    return str(v or "").strip()


def token_suffix(token: str) -> str:
    return token.split("!", 1)[-1] if "!" in token else token


def is_derivative_tick(token: str, tick: dict, index_names: Iterable[str] = ()) -> bool:
    """True when the tick belongs to an option/future contract, however the
    SDK labels it. Index feeds carry name tokens ("4.1!NIFTY 50"); a numeric
    token whose stock_name is an index name can only be a derivative."""
    if _s(tick.get("strike_price")) not in ("", "0", "0.0") or _s(tick.get("right")) or _s(tick.get("expiry_date")):
        return True
    pt = _s(tick.get("product_type")).lower()
    if pt in ("options", "futures", "option", "future"):
        return True
    ex = (_s(tick.get("exchange")) + " " + _s(tick.get("exchange_code"))).lower()
    if any(w in ex for w in _DERIV_EXCHANGE_WORDS):
        return True
    suffix = token_suffix(token)
    if suffix.isdigit() and _s(tick.get("stock_name")).upper() in {n.upper() for n in index_names}:
        return True
    return False


def parse_expiry(raw) -> Optional[str]:
    """Breeze expiry in any of its spellings → ISO date, or None."""
    s = _s(raw)
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date().isoformat()
    except ValueError:
        return None


def option_key_from_tick(tick: dict, label: str) -> Optional[str]:
    """Rebuild the app's option key (NIFTY_CE_25300_2026-11-23) from a tick's
    right/strike/expiry fields; None when any part is missing."""
    right = _s(tick.get("right")).lower()
    right = "CE" if right.startswith(("c", "ce")) else "PE" if right.startswith(("p", "pe")) else ""
    try:
        strike = int(round(float(_s(tick.get("strike_price")) or 0)))
    except ValueError:
        strike = 0
    expiry = parse_expiry(tick.get("expiry_date"))
    if not (label and right and strike > 0 and expiry):
        return None
    return f"{label}_{right}_{strike}_{expiry}"


class TickGuard:
    """Per-symbol plausibility filter. `check(key, ltp)` returns (accept, note);
    `note` is non-empty only when a decision is worth logging (first rejection
    of an episode, or acceptance of a confirmed re-base)."""

    def __init__(self, max_jump: float = 0.15, confirm_after: int = 5, agree_within: float = 0.02) -> None:
        self.max_jump = max_jump
        self.confirm_after = confirm_after
        self.agree_within = agree_within
        self._last: Dict[str, float] = {}
        self._outliers: Dict[str, list] = {}

    def check(self, key: str, ltp: float) -> Tuple[bool, str]:
        if not (ltp > 0):
            return False, ""
        last = self._last.get(key)
        if last is None or abs(ltp / last - 1.0) <= self.max_jump:
            self._last[key] = ltp
            if key in self._outliers:
                del self._outliers[key]
            return True, ""
        run = self._outliers.setdefault(key, [])
        if run and abs(ltp / run[0] - 1.0) > self.agree_within:
            run.clear()                       # outliers disagree with each other: start over
        run.append(ltp)
        if len(run) >= self.confirm_after:
            self._last[key] = ltp
            del self._outliers[key]
            return True, f"{key}: accepted re-base {last:.2f} -> {ltp:.2f} after {self.confirm_after} agreeing ticks"
        note = f"{key}: rejected {ltp:.2f} (last {last:.2f}, {abs(ltp / last - 1.0) * 100:.0f}% jump)" if len(run) == 1 else ""
        return False, note

    def reset(self, key: str) -> None:
        self._last.pop(key, None)
        self._outliers.pop(key, None)

    def seed(self, key: str, ltp: float) -> None:
        if ltp > 0:
            self._last[key] = ltp
