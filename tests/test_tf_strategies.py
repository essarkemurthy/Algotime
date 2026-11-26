"""Unit tests for strategies/common.py, orbx_nifty.py and pcl_nifty.py (pure, synthetic bars)."""
import math
import random
import unittest
from collections import Counter
from datetime import date, datetime, time, timedelta

import numpy as np

from signals import indicators as SI
from strategies import common as C
from strategies import orbx_nifty as OX
from strategies import pcl_nifty as PC
from strategies.common import LONG, SHORT, Bar

D = date(2021, 3, 10)


def bar(hh, mm, o, h, l, c, d=D):
    return Bar(datetime(d.year, d.month, d.day, hh, mm), float(o), float(h), float(l), float(c), 0)


def bars_5m(seq, start=(9, 15), d=D):
    """seq of (o, h, l, c) -> consecutive 5-minute bars from start."""
    t = datetime(d.year, d.month, d.day, *start)
    out = []
    for o, h, l, c in seq:
        out.append(Bar(t, float(o), float(h), float(l), float(c), 0))
        t += timedelta(minutes=5)
    return out


def bars_15m(seq, start=(9, 15), d=D):
    t = datetime(d.year, d.month, d.day, *start)
    out = []
    for o, h, l, c in seq:
        out.append(Bar(t, float(o), float(h), float(l), float(c), 0))
        t += timedelta(minutes=15)
    return out


class IndicatorTests(unittest.TestCase):
    def test_rsi_matches_signal_engine(self):
        rng = random.Random(3)
        closes = [100.0]
        for _ in range(120):
            closes.append(closes[-1] + rng.uniform(-2, 2))
        ours = C.rsi_wilder(closes, 14)
        ref = SI.rsi_wilder(closes, 14)
        self.assertTrue(all(v is None for v in ours[:14]))
        for a, b in zip(ours[14:], ref[14:]):
            self.assertAlmostEqual(a, b, places=9)

    def test_adx_steady_uptrend_is_100(self):
        n = 60
        highs = [i + 1.0 for i in range(n)]
        lows = [float(i) for i in range(n)]
        closes = [i + 0.5 for i in range(n)]
        adx = C.adx_wilder(highs, lows, closes, 14)
        self.assertTrue(all(v is None for v in adx[:27]))
        self.assertIsNotNone(adx[27])
        self.assertAlmostEqual(adx[-1], 100.0, places=6)

    def test_adx_flat_market_is_zero_and_short_series_undefined(self):
        n = 60
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.0] * n
        adx = C.adx_wilder(highs, lows, closes, 14)
        self.assertEqual(adx[-1], 0.0)
        self.assertTrue(all(v is None for v in C.adx_wilder(highs[:20], lows[:20], closes[:20], 14)))

    def test_adx_alternating_chop_is_low(self):
        n = 120
        highs, lows, closes = [], [], []
        for i in range(n):
            base = 100.0 + (1.0 if i % 2 else -1.0)
            highs.append(base + 1); lows.append(base - 1); closes.append(base)
        adx = C.adx_wilder(highs, lows, closes, 14)
        self.assertLess(adx[-1], 15.0)

    def test_continuous_indicators_span_sessions(self):
        d1, d2 = date(2021, 3, 9), date(2021, 3, 10)
        s1 = bars_5m([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(40)], d=d1)
        s2 = bars_5m([(140 + i, 141 + i, 139 + i, 140.5 + i) for i in range(5)], d=d2)
        ind = C.continuous_indicators({d1: s1, d2: s2}, 14, 14)
        adx2, rsi2 = ind[d2]
        self.assertEqual(len(adx2), 5)
        self.assertIsNotNone(adx2[0])          # warmed by the previous session
        self.assertGreater(rsi2[0], 90.0)

    def test_expiry_calendar(self):
        self.assertTrue(C.is_nifty_expiry_day(date(2018, 1, 25)))     # last Thursday, monthly era
        self.assertFalse(C.is_nifty_expiry_day(date(2018, 1, 18)))
        self.assertTrue(C.is_nifty_expiry_day(date(2019, 2, 14)))     # weekly Thursday
        self.assertTrue(C.is_nifty_expiry_day(date(2025, 9, 9)))      # weekly Tuesday
        self.assertFalse(C.is_nifty_expiry_day(date(2025, 9, 11)))

    def test_resample_15m(self):
        import pandas as pd
        ts = pd.date_range("2021-03-10 09:15", periods=375, freq="min")
        df = pd.DataFrame({"ts": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 0})
        out = C.resample(df, 15)
        self.assertEqual(len(out), 25)
        self.assertEqual(out["ts"].iloc[0].time(), time(9, 15))
        self.assertEqual(out["ts"].iloc[-1].time(), time(15, 15))


def _orbx_feats(atr=100.0, adx=30.0, rsi=60.0, n=75, prev_close=10000.0):
    return OX.DayFeatures(trade_date=D, prev_date=D - timedelta(days=1), prev_close=prev_close, atr=atr,
                          adx=tuple([adx] * n), rsi=tuple([rsi] * n))


def _orbx_day(breakout_close=10060.0, after=None):
    # OR 09:15-09:30: 10000-10050. Bars 3,4 inside. Bar 5 (09:40-09:45) breaks out.
    seq = [(10000, 10040, 9990, 10020), (10020, 10050, 10000, 10030), (10030, 10045, 10010, 10040),
           (10040, 10048, 10020, 10035), (10035, 10049, 10030, 10045),
           (10045, max(10052, breakout_close + 2), 10040, breakout_close)]
    seq += after or [(10060, 10070, 10050, 10065)] * 70
    return bars_5m(seq)


class OrbxTests(unittest.TestCase):
    def test_breakout_with_adx_and_rsi_fires_long(self):
        p = OX.Params()
        bars = _orbx_day()
        st = OX.DayState(D, _orbx_feats(), p)
        sig = None
        for k, b in enumerate(bars):
            sig = st.on_bar(b, k)
            if sig:
                break
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, LONG)
        self.assertEqual(sig.signal_ts.time(), time(9, 45))
        self.assertEqual(sig.or_high, 10050.0)
        self.assertAlmostEqual(sig.stop_dist, min(60.0, 0.5 * 100.0))   # OR range 60 vs 0.5 ATR = 50

    def test_adx_below_min_skips(self):
        t, why = OX.simulate_day(D, _orbx_day(), _orbx_feats(adx=15.0), OX.Params())
        self.assertIsNone(t)
        self.assertEqual(why, OX.SKIP_ADX_LOW)

    def test_rsi_wrong_side_skips(self):
        t, why = OX.simulate_day(D, _orbx_day(), _orbx_feats(rsi=45.0), OX.Params())
        self.assertIsNone(t)
        self.assertEqual(why, OX.SKIP_RSI_SIDE)

    def test_short_breakout_needs_rsi_at_or_below_line(self):
        seq = [(10000, 10040, 9990, 10020), (10020, 10050, 10000, 10030), (10030, 10045, 10010, 10040),
               (10040, 10048, 10020, 10035), (10035, 10049, 10030, 10045), (10045, 10046, 9980, 9985)]
        seq += [(9985, 9990, 9970, 9975)] * 70
        t, _ = OX.simulate_day(D, bars_5m(seq), _orbx_feats(rsi=40.0), OX.Params())
        self.assertIsNotNone(t)
        self.assertEqual(t.direction, SHORT)

    def test_no_breakout_in_window(self):
        seq = [(10000, 10040, 9990, 10020), (10020, 10050, 10000, 10030), (10030, 10045, 10010, 10040)]
        seq += [(10030, 10045, 10010, 10030)] * 72
        t, why = OX.simulate_day(D, bars_5m(seq), _orbx_feats(), OX.Params())
        self.assertIsNone(t)
        self.assertEqual(why, OX.SKIP_NO_BREAKOUT)

    def test_target_hit_and_r(self):
        after = [(10060, 10070, 10050, 10065), (10065, 10200, 10060, 10190)] + [(10190, 10195, 10185, 10190)] * 68
        t, _ = OX.simulate_day(D, _orbx_day(after=after), _orbx_feats(), OX.Params())
        self.assertEqual(t.reason, C.EXIT_TARGET)
        self.assertAlmostEqual(t.r_gross, 1.5)
        self.assertAlmostEqual(t.r_net(3.0), 1.5 - 3.0 / t.stop_dist)

    def test_time_exit(self):
        after = [(10060, 10062, 10058, 10060)] * 70
        t, _ = OX.simulate_day(D, _orbx_day(after=after), _orbx_feats(), OX.Params())
        self.assertEqual(t.reason, C.EXIT_TIME)
        self.assertEqual(t.exit_ts.time(), time(15, 15))

    def test_run_and_slices(self):
        sessions = {D: _orbx_day()}
        trades, skips = OX.run(sessions, {D: _orbx_feats()}, OX.Params())
        self.assertEqual(len(trades), 1)
        dims = OX.slice_dims(trades)
        self.assertEqual(dims["adx_at_entry"], ["30+"])        # synthetic ADX is exactly 30
        self.assertIn("expiry_day", dims)


def _pcl_feats(prev=(10000.0, 10200.0, 9900.0, 10100.0), atr=100.0, adx=30.0, rsi=60.0, n=25, p=PC.Params()):
    o, h, l, c = prev
    lv = PC.pivot_levels(h, l, c)
    ladder = PC.build_ladder(lv, atr, p.round_step, p.merge_atr)
    return PC.DayFeatures(trade_date=D, prev_date=D - timedelta(days=1), prev_close=c, atr=atr, levels=lv,
                          ladder=tuple(ladder), adx=tuple([adx] * n), rsi=tuple([rsi] * n)), lv


class PclTests(unittest.TestCase):
    def test_pivot_and_camarilla_formulas(self):
        lv = PC.pivot_levels(10200.0, 9900.0, 10100.0)
        p = (10200 + 9900 + 10100) / 3
        self.assertAlmostEqual(lv["P"], p)
        self.assertAlmostEqual(lv["R1"], 2 * p - 9900)
        self.assertAlmostEqual(lv["S1"], 2 * p - 10200)
        self.assertAlmostEqual(lv["BC"], 10050.0)
        self.assertAlmostEqual(lv["TC"], 2 * p - 10050.0)
        self.assertAlmostEqual(lv["H3"], 10100 + 1.1 * 300 / 4)
        self.assertAlmostEqual(lv["H4"], 10100 + 1.1 * 300 / 2)
        self.assertAlmostEqual(lv["L3"], 10100 - 1.1 * 300 / 4)
        self.assertAlmostEqual(lv["L4"], 10100 - 1.1 * 300 / 2)

    def test_ladder_sorted_merged_with_round_levels(self):
        f, lv = _pcl_feats()
        levels = [x for x, _ in f.ladder]
        self.assertEqual(levels, sorted(levels))
        self.assertTrue(all(b - a >= 0.05 * 100.0 - 1e-9 for a, b in zip(levels, levels[1:])))
        rounds = [x for x, t in f.ladder if t == PC.ROUND]
        self.assertTrue(all(x % 100 == 0 for x in rounds))
        self.assertGreaterEqual(min(rounds), lv["L4"] - 100.0)
        self.assertLessEqual(max(rounds), lv["H4"] + 100.0)

    def test_day_type(self):
        f, _ = _pcl_feats()
        p = PC.Params()
        quiet = bar(9, 15, 10100, 10110, 10095, 10105)
        self.assertEqual(PC.day_type_of(10100.0, quiet, f, p), PC.RANGE)
        self.assertEqual(PC.day_type_of(10250.0, quiet, f, p), PC.TREND)       # gap 150 > 1.0 ATR
        wide = bar(9, 15, 10100, 10130, 10095, 10120)                           # range 35 > 0.2 ATR
        self.assertEqual(PC.day_type_of(10100.0, wide, f, p), PC.TREND)

    def test_bias(self):
        f, lv = _pcl_feats()
        p = PC.Params()
        self.assertEqual(PC.bias_of(lv["CPR_TOP"] + 5, 30.0, 60.0, f, p), 1)
        self.assertEqual(PC.bias_of(lv["CPR_TOP"] + 5, 15.0, 60.0, f, p), 0)    # ADX too low
        self.assertEqual(PC.bias_of(lv["CPR_TOP"] + 5, 30.0, 45.0, f, p), 0)    # RSI disagrees
        self.assertEqual(PC.bias_of(lv["CPR_BOTTOM"] - 5, 30.0, 40.0, f, p), -1)
        self.assertEqual(PC.bias_of(lv["P"], 30.0, 60.0, f, p), 0)              # inside CPR

    def _trend_long_day(self, lv, after):
        # Trend day via gap (open 10250 vs prev close 10100). Bar 1 closes above R1 from below.
        r1 = lv["R1"]
        seq = [(10250, 10262, 10245, 10255),                   # bar 0: first 15m
               (10255, r1 - 1, 10250, r1 - 1),                  # bar 1: approaches R1
               (r1 - 1, r1 + 15, r1 - 3, r1 + 10)]              # bar 2: closes above R1 -> signal
        return bars_15m(seq + after)

    def test_trend_break_signal_targets_and_two_halves(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        r1 = lv["R1"]
        # After the signal: entry bar then a rally through T1 and T2.
        ladder = [x for x, _ in f.ladder]
        entry = r1 + 10
        above = [x for x in ladder if x > entry]
        t1, t2 = above[0], above[1]
        after = [(entry, entry + 5, entry - 5, entry + 2),             # entry bar
                 (entry + 2, t1 + 1, entry, t1),                        # T1 hit, stop trails to T1 - buffer
                 (t1, t2 + 1, t1 - 2, t2)] + [(t2, t2 + 1, t2 - 1, t2)] * 20   # T2 hit
        trades, skips = PC.simulate_day(D, self._trend_long_day(lv, after), f, p)
        self.assertEqual(len(trades), 1, skips)
        t = trades[0]
        self.assertEqual((t.direction, t.day_type, t.level_type), (LONG, PC.TREND, PC.PIVOT))
        self.assertEqual(t.entry, entry)
        self.assertEqual((t.t1, t.t2), (t1, t2))
        self.assertEqual(t.reason, "T1/T2")
        below = max(x for x in ladder if x < entry)
        self.assertAlmostEqual(t.stop_dist, entry - (below - 0.15 * 100.0))
        self.assertAlmostEqual(t.exit, (t1 + t2) / 2)
        self.assertAlmostEqual(t.r_gross, ((t1 + t2) / 2 - entry) / t.stop_dist)

    def test_trailing_stop_after_t1(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        r1 = lv["R1"]
        ladder = [x for x, _ in f.ladder]
        entry = r1 + 10
        above = [x for x in ladder if x > entry]
        t1 = above[0]
        trail = t1 - 0.15 * 100.0
        after = [(entry, entry + 5, entry - 5, entry + 2),
                 (entry + 2, t1 + 1, entry, t1 + 0.5),              # T1 hit; trailing stop pending
                 (t1, t1 + 2, trail - 1, trail)] + [(trail, trail + 1, trail - 1, trail)] * 20
        trades, _ = PC.simulate_day(D, self._trend_long_day(lv, after), f, p)
        self.assertEqual(trades[0].reason, "T1/trail")
        self.assertAlmostEqual(trades[0].exit, (t1 + trail) / 2)

    def test_rr_too_low_skips_and_counts(self):
        p = PC.Params(rr_min=50.0)                 # impossible reward:risk -> every signal skipped
        f, lv = _pcl_feats()
        entry = lv["R1"] + 10
        trades, skips = PC.simulate_day(D, self._trend_long_day(lv, [(entry, entry + 1, entry - 1, entry)] * 22), f, p)
        self.assertEqual(trades, [])
        self.assertEqual(skips["rr_too_low"], 1)

    def test_range_failed_test_long(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        s1 = lv["S1"]
        # Range day: open at prev close, quiet first bar. Bar 1 above S1; bar 2 dips below S1 and closes back above.
        seq = [(10100, 10108, 10094, 10102), (10102, 10105, s1 + 5, s1 + 6), (s1 + 6, s1 + 8, s1 - 10, s1 + 4)]
        entry = s1 + 4
        seq += [(entry, entry + 1, entry - 1, entry)] * 22
        trades, skips = PC.simulate_day(D, bars_15m(seq), f, p)
        self.assertEqual(len(trades), 1, skips)
        t = trades[0]
        self.assertEqual((t.direction, t.day_type, t.level_type), (LONG, PC.RANGE, PC.PIVOT))
        self.assertEqual(t.reason, "time/time")
        self.assertEqual(t.exit_ts.time(), time(15, 0))

    def test_trend_day_ignores_failed_tests_and_range_day_ignores_breaks(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        r1 = lv["R1"]
        # Range day (no gap, quiet first bar) with a clean R1 break: no trend entry allowed.
        seq = [(10100, 10108, 10094, 10102), (10102, r1 - 1, 10100, r1 - 1), (r1 - 1, r1 + 15, r1 - 3, r1 + 10)]
        seq += [(r1 + 10, r1 + 11, r1 + 9, r1 + 10)] * 22
        trades, skips = PC.simulate_day(D, bars_15m(seq), f, p)
        self.assertEqual(trades, [])
        self.assertEqual(skips[PC.SKIP_NO_SIGNAL], 1)

    def test_max_two_entries_per_day(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        r1 = lv["R1"]
        ladder = [x for x, _ in f.ladder]
        entry = r1 + 10
        below = max(x for x in ladder if x < entry)
        stop = below - 15.0
        # Signal, entry, immediate stop-out, then the same break again twice more; only two trades.
        cycle = [(10255, r1 - 1, 10250, r1 - 1), (r1 - 1, r1 + 15, r1 - 3, r1 + 10),
                 (entry, entry + 1, stop - 1, stop)]
        seq = [(10250, 10262, 10245, 10255)] + cycle * 3 + [(stop, stop + 1, stop - 1, stop)] * 10
        trades, _ = PC.simulate_day(D, bars_15m(seq), f, p)
        self.assertEqual(len(trades), 2)
        self.assertEqual([t.seq for t in trades], [1, 2])
        self.assertTrue(all(t.reason == "stop/stop" for t in trades))

    def test_run_slices_rows(self):
        p = PC.Params()
        f, lv = _pcl_feats()
        entry = lv["R1"] + 10
        bars = self._trend_long_day(lv, [(entry, entry + 1, entry - 1, entry)] * 22)
        trades, skips = PC.run({D: bars}, {D: f}, p)
        self.assertEqual(len(trades), 1)
        dims = PC.slice_dims(trades)
        self.assertEqual(dims["day_type"], [PC.TREND])
        row = PC.trade_row(trades[0])
        self.assertIn("r_net_3", row)


if __name__ == "__main__":
    unittest.main()
