from datetime import datetime
from typing import Dict, Optional


class CandleBuilder:
    """
    Aggregates raw price ticks into OHLCV candles entirely in memory.
    One open candle per key at any time. Returns a completed candle dict
    when the minute rolls over.

    The key is anything hashable: a symbol string for spot, or a
    (symbol, expiry) tuple for futures.
    """

    def __init__(self, interval: str = "1m") -> None:
        self._open: Dict = {}
        self._interval   = interval

    def update(self, key, symbol: str, ts: datetime, ltp: float, volume: int,
               extra: Optional[dict] = None) -> Optional[dict]:
        """
        Feed a tick. Returns a completed candle if the minute rolled over, else None.
        extra: additional fields to include in the candle dict (e.g. expiry for futures).
        """
        candle_ts = ts.replace(second=0, microsecond=0)

        if key not in self._open:
            self._open[key] = _new_candle(symbol, candle_ts, ltp, volume, self._interval, extra)
            return None

        current = self._open[key]

        if candle_ts > current["ts"]:
            completed = current.copy()
            self._open[key] = _new_candle(symbol, candle_ts, ltp, volume, self._interval, extra)
            return completed

        current["high"]   = max(current["high"], ltp)
        current["low"]    = min(current["low"],  ltp)
        current["close"]  = ltp
        current["volume"] = volume
        return None

    def flush_all(self) -> list:
        """Force-return all open (incomplete) candles — call at shutdown."""
        candles = list(self._open.values())
        self._open.clear()
        return candles


def _new_candle(symbol: str, ts: datetime, ltp: float, volume: int,
                interval: str, extra: Optional[dict]) -> dict:
    candle = {
        "symbol": symbol, "ts": ts, "interval": interval,
        "open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": volume,
    }
    if extra:
        candle.update(extra)
    return candle
