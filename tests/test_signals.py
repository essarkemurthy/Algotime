"""
Unit tests for the signals package — indicators, detectors, aggregator, engine.

Run:  python -m unittest tests.test_signals          (stdlib, no pytest needed)
or:   python -m unittest discover -s tests
"""

import math
import unittest
from datetime import date, datetime, time, timedelta

import numpy as np

from signals.aggregator import BarAggregator
from signals.config import SignalConfig
from signals.detectors import (LONG, ORB, SHORT, VWAP_REV, detect_orb,
                               detect_vwap_reversal)
from signals.engine import SignalEngine
from signals.indicators import (atr_wilder, cumulative_vwap, rolling_mean,
                                rsi_wilder)
from signals.session import SymbolSession

TRADE_DATE = date(2026, 6, 25)
OPEN_TS = datetime(2026, 6, 25, 9, 15)


def make_session(closes, cfg, *, vol=100, spread=0.5, vols=None):
    """Build a SymbolSession from a list of closes. H=C+spread, L=C-spread so
    typical price ≈ close, keeping VWAP math easy to reason about."""
    sess = SymbolSession(symbol="TEST", cfg=cfg, trade_date=TRADE_DATE)
    for i, c in enumerate(closes):
        v = vol if vols is None else vols[i]
        sess.add_bar({
            "ts":   OPEN_TS + timedelta(minutes=5 * i),
            "open": c, "high": c + spread, "low": c - spread,
            "close": c, "volume": v,
        })
    return sess


def small_cfg(**over):
    """A config with short warm-up periods so fixtures stay tiny."""
    cfg = SignalConfig()
    cfg.rsi_period = 2
    cfg.atr_period = 2
    cfg.avg_vol_period = 2
    cfg.stretch_atr = 1.0
    cfg.bar_interval = "5m"
    cfg.orb_minutes = 15            # → 3 bars opening range at 5m
    cfg.vol_mult = 1.5
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# ── Indicators ────────────────────────────────────────────────────────────────

class TestIndicators(unittest.TestCase):
    def test_rsi_all_gains_is_100(self):
        rsi = rsi_wilder([1, 2, 3, 4, 5, 6], period=3)
        self.assertEqual(rsi[-1], 100.0)

    def test_rsi_known_value(self):
        # Classic Wilder example prefix — RSI should land in a sane mid band.
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        rsi = rsi_wilder(closes, period=14)
        self.assertTrue(70 <= rsi[-1] <= 75, f"RSI={rsi[-1]}")

    def test_atr_constant_range(self):
        # Flat series with a fixed 2-point bar range → ATR converges to 2.
        highs = [11] * 10
        lows = [9] * 10
        closes = [10] * 10
        atr = atr_wilder(highs, lows, closes, period=3)
        self.assertAlmostEqual(atr[-1], 2.0, places=6)

    def test_vwap_matches_manual(self):
        h = [10, 12]; l = [8, 10]; c = [9, 11]; v = [100, 300]
        # tp = [9, 11]; vwap[1] = (9*100 + 11*300)/400 = 10.5
        vwap = cumulative_vwap(h, l, c, v)
        self.assertAlmostEqual(vwap[0], 9.0)
        self.assertAlmostEqual(vwap[1], 10.5)

    def test_vwap_zero_volume_fallback(self):
        vwap = cumulative_vwap([10, 12], [8, 10], [9, 11], [0, 0])
        self.assertAlmostEqual(vwap[1], 10.0)   # mean typical price (9,11)

    def test_rolling_mean(self):
        rm = rolling_mean([2, 4, 6, 8], period=2)
        self.assertTrue(math.isnan(rm[0]))
        self.assertAlmostEqual(rm[1], 3.0)
        self.assertAlmostEqual(rm[3], 7.0)


# ── VWAP Reversal ──────────────────────────────────────────────────────────────

class TestVwapReversal(unittest.TestCase):
    def test_bullish_fires(self):
        cfg = small_cfg(bull_rsi_low=0, bull_rsi_high=100)
        # down (stretch below VWAP) then a strong pop back above VWAP
        sess = make_session([100, 98, 96, 94, 92, 99], cfg)
        sig = detect_vwap_reversal(sess)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, LONG)
        self.assertEqual(sig.strategy, VWAP_REV)
        self.assertGreater(sig.trigger_price, sig.vwap)

    def test_bearish_fires(self):
        cfg = small_cfg(bear_rsi_low=0, bear_rsi_high=100)
        sess = make_session([100, 102, 104, 106, 108, 101], cfg)
        sig = detect_vwap_reversal(sess)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, SHORT)
        self.assertLess(sig.trigger_price, sig.vwap)

    def test_rsi_band_suppresses(self):
        # Same bullish path, but an impossible RSI band → no signal.
        cfg = small_cfg(bull_rsi_low=99, bull_rsi_high=100)
        sess = make_session([100, 98, 96, 94, 92, 99], cfg)
        self.assertIsNone(detect_vwap_reversal(sess))

    def test_no_stretch_no_signal(self):
        # Gentle wander that never stretches a full ATR below VWAP.
        cfg = small_cfg(bull_rsi_low=0, bull_rsi_high=100, stretch_atr=10.0)
        sess = make_session([100, 100, 100, 100, 100, 101], cfg)
        self.assertIsNone(detect_vwap_reversal(sess))


# ── ORB ─────────────────────────────────────────────────────────────────────────

class TestORB(unittest.TestCase):
    def test_long_breakout_fires(self):
        cfg = small_cfg()
        # 3 range bars ~100, then a high-volume close above the range high.
        sess = make_session([100, 101, 100, 105], cfg,
                            vols=[100, 100, 100, 300])
        sig = detect_orb(sess)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, LONG)
        self.assertEqual(sig.strategy, ORB)
        self.assertGreaterEqual(sig.vol_ratio, cfg.vol_mult)

    def test_short_breakout_fires(self):
        cfg = small_cfg()
        sess = make_session([100, 99, 100, 95], cfg, vols=[100, 100, 100, 300])
        sig = detect_orb(sess)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, SHORT)

    def test_low_volume_suppresses(self):
        cfg = small_cfg()
        sess = make_session([100, 101, 100, 105], cfg,
                            vols=[100, 100, 100, 110])   # ratio 1.1 < 1.5
        self.assertIsNone(detect_orb(sess))

    def test_no_breakout_inside_range(self):
        cfg = small_cfg()
        sess = make_session([100, 101, 100, 100.5], cfg,
                            vols=[100, 100, 100, 300])
        self.assertIsNone(detect_orb(sess))


# ── Aggregator ──────────────────────────────────────────────────────────────────

class TestAggregator(unittest.TestCase):
    def test_per_bar_volume_via_differencing(self):
        agg = BarAggregator(interval_minutes=5, session_start=time(9, 15))
        base = datetime(2026, 6, 25, 9, 15)
        # cumulative volume grows 1000 → 1000 → 1200 within bar 1
        self.assertIsNone(agg.update("X", base, 100.0, 1000))           # first tick (baseline)
        self.assertIsNone(agg.update("X", base + timedelta(seconds=30), 101.0, 1100))
        bar = agg.update("X", base + timedelta(minutes=5), 102.0, 1300)  # rolls bar 1
        self.assertIsNotNone(bar)
        self.assertEqual(bar["volume"], 100.0)   # 1100-1000 within the bar
        self.assertEqual(bar["open"], 100.0)
        self.assertEqual(bar["high"], 101.0)
        self.assertEqual(bar["ts"], base)

    def test_preopen_ignored(self):
        agg = BarAggregator(interval_minutes=5, session_start=time(9, 15))
        pre = datetime(2026, 6, 25, 9, 10)
        self.assertIsNone(agg.update("X", pre, 100.0, 500))

    def test_bucket_anchored_to_open(self):
        agg = BarAggregator(interval_minutes=30, session_start=time(9, 15))
        base = datetime(2026, 6, 25, 9, 15)
        agg.update("X", base, 100.0, 0)
        # 09:44 still in the first 09:15–09:45 bucket → no completed bar
        self.assertIsNone(agg.update("X", datetime(2026, 6, 25, 9, 44), 101.0, 10))
        bar = agg.update("X", datetime(2026, 6, 25, 9, 45), 102.0, 20)
        self.assertIsNotNone(bar)
        self.assertEqual(bar["ts"], base)


# ── Engine: dedup, kill-switch, dry-run, DB-less logging ───────────────────────

class TestEngine(unittest.TestCase):
    def _orb_bars(self, cfg):
        closes = [100, 101, 100, 105, 106]
        vols = [100, 100, 100, 300, 300]
        out = []
        for i, c in enumerate(closes):
            out.append((f"bar{i}", {
                "ts": OPEN_TS + timedelta(minutes=5 * i),
                "open": c, "high": c + 0.5, "low": c - 0.5,
                "close": c, "volume": vols[i],
            }))
        return out

    def test_dedup_first_only(self):
        cfg = small_cfg()
        sent = []
        eng = SignalEngine(cfg, store=None, broadcast_fn=lambda p: sent.append(p))
        fired_total = 0
        for _, bar in self._orb_bars(cfg):
            fired_total += len(eng.on_bar_close("TEST", bar))
        # Two consecutive bars close above the range, but only the first fires.
        orb_signals = [p for p in sent if p["strategy"] == ORB]
        self.assertEqual(len(orb_signals), 1)
        self.assertEqual(fired_total, 1)

    def test_killswitch_logs_but_does_not_notify(self):
        cfg = small_cfg(enabled=False)
        sent = []
        eng = SignalEngine(cfg, store=None, broadcast_fn=lambda p: sent.append(p))
        for _, bar in self._orb_bars(cfg):
            eng.on_bar_close("TEST", bar)
        self.assertEqual(sent, [])              # nothing notified
        self.assertTrue(len(eng.recent) >= 1)   # but still recorded

    def test_dry_run_does_not_notify(self):
        cfg = small_cfg(dry_run=True)
        sent = []
        eng = SignalEngine(cfg, store=None, broadcast_fn=lambda p: sent.append(p))
        for _, bar in self._orb_bars(cfg):
            eng.on_bar_close("TEST", bar)
        self.assertEqual(sent, [])
        self.assertTrue(len(eng.recent) >= 1)

    def test_day_boundary_resets_state(self):
        cfg = small_cfg()
        eng = SignalEngine(cfg, store=None, broadcast_fn=lambda p: None)
        for _, bar in self._orb_bars(cfg):
            eng.on_bar_close("TEST", bar)
        # Next day, same shape → a fresh signal is allowed again.
        next_day = OPEN_TS + timedelta(days=1)
        closes = [100, 101, 100, 105]; vols = [100, 100, 100, 300]
        fired = 0
        for i, c in enumerate(closes):
            fired += len(eng.on_bar_close("TEST", {
                "ts": next_day + timedelta(minutes=5 * i),
                "open": c, "high": c + 0.5, "low": c - 0.5,
                "close": c, "volume": vols[i],
            }))
        self.assertEqual(fired, 1)


if __name__ == "__main__":
    unittest.main()
