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
        orb_fired = 0
        for _, bar in self._orb_bars(cfg):
            orb_fired += sum(1 for s in eng.on_bar_close("TEST", bar) if s.strategy == ORB)
        # Two consecutive bars close above the range, but only the first fires.
        orb_signals = [p for p in sent if p["strategy"] == ORB]
        self.assertEqual(len(orb_signals), 1)
        self.assertEqual(orb_fired, 1)

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
        orb_fired = 0
        for i, c in enumerate(closes):
            orb_fired += sum(1 for s in eng.on_bar_close("TEST", {
                "ts": next_day + timedelta(minutes=5 * i),
                "open": c, "high": c + 0.5, "low": c - 0.5,
                "close": c, "volume": vols[i],
            }) if s.strategy == ORB)
        self.assertEqual(orb_fired, 1)


# ── New indicators ─────────────────────────────────────────────────────────────

class TestNewIndicators(unittest.TestCase):
    def test_ema_seed_and_recursion(self):
        from signals.indicators import ema
        v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10.0]
        out = ema(v, 3)
        self.assertTrue(np.isnan(out[1]))
        self.assertAlmostEqual(out[2], 2.0)            # seed = mean(1,2,3)
        k = 2 / (3 + 1)
        self.assertAlmostEqual(out[3], 4 * k + 2 * (1 - k))

    def test_rolling_std_matches_numpy(self):
        from signals.indicators import rolling_std
        v = np.array([2, 4, 4, 4, 5, 5, 7, 9.0])
        out = rolling_std(v, 4)
        self.assertAlmostEqual(out[3], v[:4].std())
        self.assertAlmostEqual(out[-1], v[-4:].std())

    def test_bollinger_bands(self):
        from signals.indicators import bollinger_bands
        c = np.arange(1, 30, dtype=float)
        mid, up, lo = bollinger_bands(c, 20, 2.0)
        self.assertTrue(np.isnan(mid[18]))
        self.assertAlmostEqual(mid[19], c[:20].mean())
        self.assertTrue(up[19] > mid[19] > lo[19])

    def test_supertrend_trend_direction(self):
        from signals.indicators import supertrend
        # steady uptrend → direction should settle to +1
        c = np.arange(1, 40, dtype=float)
        _line, d = supertrend(c + 0.5, c - 0.5, c, 10, 3.0)
        self.assertEqual(d[-1], 1)

    def test_donchian_prior_window(self):
        from signals.indicators import donchian
        h = np.array([1, 2, 3, 4, 5, 6.0])
        l = h - 1
        up, dn = donchian(h, l, 3)
        self.assertTrue(np.isnan(up[2]))
        self.assertEqual(up[3], 3.0)   # max high of bars 0..2
        self.assertEqual(dn[3], 0.0)   # min low of bars 0..2


# ── New detectors fire on constructed setups ───────────────────────────────────

class TestNewDetectors(unittest.TestCase):
    def test_ema_crossover_long(self):
        from signals.detectors import detect_ema_crossover, LONG
        cfg = small_cfg(); cfg.ema_fast = 2; cfg.ema_slow = 3
        # down then sharply up → fast EMA crosses above slow
        closes = [10, 9, 8, 7, 6, 5, 6, 8, 11, 15.0]
        sess = make_session(closes, cfg)
        found = None
        for i in range(1, len(closes)):
            s = make_session(closes[:i + 1], cfg)
            sig = detect_ema_crossover(s)
            if sig:
                found = sig
        self.assertIsNotNone(found)
        self.assertEqual(found.direction, LONG)

    def test_donchian_breakout_needs_volume(self):
        from signals.detectors import detect_donchian, LONG
        cfg = small_cfg(); cfg.dc_period = 3; cfg.vol_mult = 1.5
        closes = [10, 10, 10, 10, 12.0]          # last bar breaks 3-bar high
        # low volume on breakout → suppressed
        lo_vol = make_session(closes, cfg, vols=[100, 100, 100, 100, 100])
        self.assertIsNone(detect_donchian(lo_vol))
        # high volume on breakout → fires long
        hi_vol = make_session(closes, cfg, vols=[100, 100, 100, 100, 500])
        sig = detect_donchian(hi_vol)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, LONG)

    def test_vwap_orb_confluence_long(self):
        from signals.detectors import detect_vwap_orb, LONG
        cfg = small_cfg()                         # 3-bar opening range, vol_mult 1.5
        closes = [10, 10, 10, 11, 13.0]           # breakout above OR-high, trend up
        # low volume on the breakout bar → suppressed (needs volume confirmation)
        lo_vol = make_session(closes, cfg, vols=[100, 100, 100, 100, 100])
        self.assertIsNone(detect_vwap_orb(lo_vol))
        # high-volume breakout, above VWAP, RSI on-side → fires long
        hi_vol = make_session(closes, cfg, vols=[100, 100, 100, 100, 500])
        sig = detect_vwap_orb(hi_vol)
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, LONG)
        self.assertEqual(sig.strategy, "VWAP_ORB")


if __name__ == "__main__":
    unittest.main()
