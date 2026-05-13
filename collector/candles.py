from datetime import datetime
from typing import Dict, Optional


class CandleBuilder:
    """
    Aggregates raw spot ticks into 1-minute OHLCV candles entirely in memory.
    One open candle per symbol at any time.
    Returns a completed candle dict when the minute rolls over.
    """

    def __init__(self) -> None:
        self._open: Dict[str, dict] = {}

    def update(
        self, symbol: str, ts: datetime, ltp: float, volume: int
    ) -> Optional[dict]:
        """
        Feed a tick. Returns a completed candle if the minute just rolled over, else None.
        The completed candle should be written to the DB by the caller.
        """
        candle_ts = ts.replace(second=0, microsecond=0)

        if symbol not in self._open:
            self._open[symbol] = _new_candle(symbol, candle_ts, ltp, volume)
            return None

        current = self._open[symbol]

        if candle_ts > current["ts"]:
            completed = current.copy()
            self._open[symbol] = _new_candle(symbol, candle_ts, ltp, volume)
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


def _new_candle(symbol: str, ts: datetime, ltp: float, volume: int) -> dict:
    return {
        "symbol": symbol, "ts": ts,
        "open": ltp, "high": ltp, "low": ltp, "close": ltp,
        "volume": volume,
    }
