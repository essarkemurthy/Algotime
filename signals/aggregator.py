"""
signals/aggregator.py — tick → interval OHLCV bars with true per-bar volume.

Why not reuse collector.candles.CandleBuilder directly? That builder stores the
*last cumulative* day volume as the bar's volume, which is the right choice for
the collector's persistence but wrong for ORB / average-volume gating, which
need genuine per-bar traded volume. This aggregator keeps the same "emit a
completed bar when the bucket rolls over" contract but derives per-bar volume
by differencing the cumulative traded-quantity field across ticks.

Bars are anchored to the session open (09:15 IST) so every interval lines up
with NSE's session-anchored bars (e.g. 30m → 09:15, 09:45, …), matching the
historical candles already in the DB. Pre-open ticks are ignored.
"""

from datetime import date, datetime, time as time_t, timedelta
from typing import Dict, Optional


class BarAggregator:
    def __init__(self, interval_minutes: int, session_start: time_t) -> None:
        self._interval = interval_minutes
        self._session_start = session_start
        self._open: Dict[str, dict] = {}      # symbol → forming bar
        self._last_cum: Dict[str, float] = {}  # symbol → last cumulative volume seen

    def _bucket_start(self, ts: datetime) -> Optional[datetime]:
        """Floor `ts` to the interval, anchored at the session open. None if pre-open."""
        open_dt = datetime.combine(ts.date(), self._session_start)
        if ts < open_dt:
            return None
        mins = int((ts - open_dt).total_seconds() // 60)
        idx = mins // self._interval
        return open_dt + timedelta(minutes=idx * self._interval)

    def update(self, symbol: str, ts: datetime, price: float,
               cum_volume: Optional[float]) -> Optional[dict]:
        """Feed one tick. Returns a completed bar dict when the bucket rolls over.

        cum_volume is the cumulative day traded quantity from the feed (ttq /
        total_traded_volume). Pass None when the feed has no volume.
        """
        bucket = self._bucket_start(ts)
        if bucket is None:
            return None

        # Per-bar volume via cumulative differencing.
        prev = self._last_cum.get(symbol)
        if cum_volume is None or prev is None:
            delta = 0.0
        else:
            delta = max(0.0, float(cum_volume) - prev)
        if cum_volume is not None:
            self._last_cum[symbol] = float(cum_volume)

        cur = self._open.get(symbol)
        completed: Optional[dict] = None

        if cur is None or bucket > cur["ts"]:
            if cur is not None and bucket > cur["ts"]:
                completed = cur
            self._open[symbol] = {
                "ts": bucket, "open": price, "high": price,
                "low": price, "close": price, "volume": delta,
            }
        else:
            cur["high"]   = max(cur["high"], price)
            cur["low"]    = min(cur["low"], price)
            cur["close"]  = price
            cur["volume"] += delta

        return completed

    def flush(self, symbol: str) -> Optional[dict]:
        """Force-return the open (incomplete) bar for a symbol, if any."""
        return self._open.pop(symbol, None)

    def reset(self) -> None:
        self._open.clear()
        self._last_cum.clear()
