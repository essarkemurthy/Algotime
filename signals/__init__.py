"""
signals — real-time intraday signal detection (VWAP Reversal + ORB).

Read-only alerting layer: detects signals on freshly-closed bars and dispatches
notifications. It NEVER places, modifies, or routes orders — by design there is
no import of any broker/order path in this package.

Public surface:
    SignalConfig   — env-driven thresholds (signals.config)
    SignalEngine   — on_bar_close() entry point (signals.engine)
    Signal         — a detected signal record (signals.detectors)
    BarAggregator  — tick → interval OHLCV with true per-bar volume (signals.aggregator)
"""

from .config import SignalConfig
from .detectors import Signal
from .engine import SignalEngine
from .aggregator import BarAggregator

__all__ = ["SignalConfig", "SignalEngine", "Signal", "BarAggregator"]
