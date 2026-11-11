"""
Unit tests for strategies/orb_cpr_nifty.py (ORB-CPR-15 on NIFTY).

Run:  python -m unittest tests.test_orb_cpr
or:   python -m unittest discover -s tests
"""

import math
import unittest
from datetime import date, datetime, time, timedelta

import pandas as pd

from strategies import orb_cpr_nifty as S
from strategies.orb_cpr_nifty import (LONG, SHORT, Bar, DayFeatures, DayState, Params,
                                      SpreadParams)

D = date(2026, 6, 25)
P = Params()


def mk_bars(d, closes, spread=2.0, start=time(9, 15)):
    """75 (or len(closes)) five-minute bars; H = C+spread, L = C-spread, O = prev C."""
    bars, prev = [], closes[0]
    t0 = datetime.combine(d, start)
    for i, c in enumerate(closes):
        bars.append(Bar(t0 + timedelta(minutes=5 * i), prev, max(prev, c) + spread,
                        min(prev, c) - spread, c, 100))
        prev = c
    return bars


def flat_session(d, level, n=75, spread=2.0):
    return mk_bars(d, [level] * n, spread)


def feats(prev_close=100.0, atr=10.0, cpr_top=101.0, cpr_bottom=99.0, d=D, width=None):
    if width is None:
        width = abs(cpr_top - cpr_bottom) / prev_close * 100.0
    return DayFeatures(trade_date=d, prev_date=d - timedelta(days=1), prev_open=prev_close,
                       prev_high=prev_close + 5, prev_low=prev_close - 5, prev_close=prev_close,
                       pivot=(cpr_top + cpr_bottom) / 2, cpr_top=cpr_top, cpr_bottom=cpr_bottom,
                       cpr_width_pct=width, atr=atr)


def or_then(d, or_level, breakout_at, breakout_close, after=None, spread=1.0):
    """Three OR bars at `or_level` (range = 2*spread), then flat bars until the
    bar opening at `breakout_at` closes at `breakout_close`; `after` = closes of
    the remaining bars (default flat at breakout_close)."""
    closes, t = [], time(9, 15)
    while t < breakout_at:
        closes.append(or_level)
        t = S._add_minutes(t, 5)
    closes.append(breakout_close)
    rest = 75 - len(closes)
    closes += (after or [breakout_close] * rest)[:rest]
    return mk_bars(d, closes, spread)


class TestFeatures(unittest.TestCase):
    def test_cpr_math(self):
        p, top, bottom, width = S.cpr(110, 90, 105)
        self.assertAlmostEqual(p, (110 + 90 + 105) / 3)
        bc, tc = 100.0, 2 * p - 100.0
        self.assertAlmostEqual(top, max(tc, bc))
        self.assertAlmostEqual(bottom, min(tc, bc))
        self.assertAlmostEqual(width, abs(tc - bc) / 105 * 100)

    def test_atr_wilder(self):
        h = [12.0] * 20; l = [10.0] * 20; c = [11.0] * 20
        atrs = S.atr_wilder(h, l, c, 14)
        self.assertEqual(atrs[:13], [None] * 13)
        self.assertAlmostEqual(atrs[13], 2.0)
        self.assertAlmostEqual(atrs[19], 2.0)
        # a spike decays with Wilder smoothing: (13*2 + 16)/14
        h2 = h[:]; l2 = l[:]; h2[15] = 26.0
        atrs2 = S.atr_wilder(h2, l2, c, 14)
        self.assertAlmostEqual(atrs2[15], (13 * 2 + 16) / 14)

    def _sessions(self, n=20, level=100.0):
        out = {}
        d = date(2026, 1, 5)
        for i in range(n):
            while d.weekday() >= 5:
                d += timedelta(days=1)
            out[d] = flat_session(d, level + i, spread=2.0)
            d += timedelta(days=1)
        return out

    def test_daily_features_use_previous_session_only(self):
        sess = self._sessions()
        f = S.daily_features(sess, P)
        days = sorted(sess)
        self.assertNotIn(days[0], f)              # no previous session
        self.assertNotIn(days[13], f)             # ATR needs 14 prior sessions
        self.assertIn(days[14], f)
        self.assertEqual(f[days[14]].prev_date, days[13])
        self.assertAlmostEqual(f[days[14]].prev_close, 100 + 13)

    def test_no_lookahead(self):
        sess = self._sessions()
        days = sorted(sess)
        base = S.daily_features(sess, P)
        t = days[16]
        mutated = dict(sess)
        mutated[t] = mk_bars(t, [500.0] * 75, spread=50.0)       # wild day t
        f2 = S.daily_features(mutated, P)
        self.assertEqual(base[t], f2[t])                          # day t unchanged
        self.assertNotEqual(base[days[17]], f2[days[17]])         # day t+1 sees it

    def test_special_session_excluded(self):
        sess = self._sessions()
        days = sorted(sess)
        short_day = days[15]
        sess[short_day] = flat_session(short_day, 999.0, n=40)    # Muhurat-like
        kept = S.split_sessions(pd.DataFrame(
            [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": 0}
             for d in sess for b in sess[d]]), P)
        self.assertNotIn(short_day, kept)
        f = S.daily_features(kept, P)
        self.assertEqual(f[days[16]].prev_date, days[14])         # skips the special day
        self.assertNotIn(short_day, f)

    def test_resample_5m_anchor_and_tz(self):
        ts = pd.date_range("2026-06-25 09:15", "2026-06-25 15:30", freq="1min", tz="Asia/Kolkata")
        df = pd.DataFrame({"ts": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1})
        df.loc[df.index[3], "high"] = 9.0                         # 09:18 belongs to the 09:15 bar
        out = S.resample_5m(df, P)
        self.assertEqual(len(out), 75)
        self.assertEqual(out["ts"].iloc[0], pd.Timestamp("2026-06-25 09:15"))
        self.assertEqual(out["ts"].iloc[-1], pd.Timestamp("2026-06-25 15:25"))
        self.assertEqual(out["high"].iloc[0], 9.0)
        self.assertEqual(int(out["volume"].iloc[0]), 5)


class TestFilters(unittest.TestCase):
    def run_day(self, bars, f):
        return S.simulate_day(D, bars, f, P)

    def test_gap_skip(self):
        bars = flat_session(D, 120.0)                              # open 120 vs prev close 100, ATR 10
        res = self.run_day(bars, feats(cpr_top=100.3, cpr_bottom=99.7))
        self.assertEqual(res.skip_reason, S.SKIP_GAP)
        self.assertIsNone(res.signal)

    def test_cpr_wide_skip(self):
        res = self.run_day(flat_session(D, 100.0), feats(cpr_top=101.0, cpr_bottom=99.0))  # 2% wide
        self.assertEqual(res.skip_reason, S.SKIP_CPR_WIDE)

    def test_or_too_small(self):
        bars = flat_session(D, 100.0, spread=0.5)                  # OR range 1 < 0.2*ATR
        res = self.run_day(bars, feats(cpr_top=100.3, cpr_bottom=99.7))
        self.assertEqual(res.skip_reason, S.SKIP_OR_SMALL)

    def test_or_too_large(self):
        bars = flat_session(D, 100.0, spread=4.0)                  # OR range 8 > 0.6*ATR
        res = self.run_day(bars, feats(cpr_top=100.3, cpr_bottom=99.7))
        self.assertEqual(res.skip_reason, S.SKIP_OR_LARGE)

    def test_no_features_skip(self):
        res = self.run_day(flat_session(D, 100.0), None)
        self.assertEqual(res.skip_reason, S.SKIP_NO_FEATURES)

    def test_no_breakout(self):
        bars = flat_session(D, 100.0, spread=1.5)                  # OR range 3 = 0.3 ATR
        res = self.run_day(bars, feats(cpr_top=100.3, cpr_bottom=99.7))
        self.assertEqual(res.skip_reason, S.SKIP_NO_BREAKOUT)


class TestSignals(unittest.TestCase):
    F = feats(cpr_top=100.3, cpr_bottom=99.7)                      # OR 99..101 with spread 1

    def test_long_signal_entry_next_bar(self):
        bars = or_then(D, 100.0, time(9, 45), 103.0, after=[103.0] * 70)
        res = S.simulate_day(D, bars, self.F, P)
        sig, tr = res.signal, res.trade
        self.assertEqual(sig.direction, LONG)
        self.assertEqual(sig.signal_ts, datetime.combine(D, time(9, 50)))   # bar close
        self.assertAlmostEqual(sig.or_high, 101.0); self.assertAlmostEqual(sig.or_low, 99.0)
        self.assertAlmostEqual(sig.stop_dist, min(2.0, 0.5 * 10.0))         # min(OR, 0.5 ATR)
        self.assertEqual(tr.entry_ts, datetime.combine(D, time(9, 50)))
        self.assertAlmostEqual(tr.entry, bars[7].open)                       # next bar open

    def test_short_signal_needs_cpr_bottom(self):
        f = feats(cpr_top=100.3, cpr_bottom=97.0, width=0.2)                 # bottom below the break
        bars = or_then(D, 100.0, time(9, 45), 98.0)
        self.assertIsNone(S.simulate_day(D, bars, f, P).signal)              # below ORL, not CPR
        bars = or_then(D, 100.0, time(9, 45), 96.0)
        self.assertEqual(S.simulate_day(D, bars, f, P).signal.direction, SHORT)

    def test_one_signal_per_day_and_idempotent(self):
        bars = or_then(D, 100.0, time(9, 45), 103.0, after=[103.0, 96.0, 103.0, 96.0] * 18)
        st = DayState(D, self.F, P)
        fired = [st.on_bar(b) for b in bars]
        self.assertEqual(sum(1 for x in fired if x is not None), 1)
        self.assertTrue(st.decided)
        self.assertIsNone(st.on_bar(bars[-1]))                               # after restart replay

    def test_window_boundaries(self):
        # bar opening 09:30 closes 09:35 -> eligible; bar opening 11:00 closes 11:05 -> not
        bars = or_then(D, 100.0, time(9, 30), 103.0)
        self.assertEqual(S.simulate_day(D, bars, self.F, P).signal.direction, LONG)
        bars = or_then(D, 100.0, time(11, 0), 103.0)
        res = S.simulate_day(D, bars, self.F, P)
        self.assertIsNone(res.signal)
        self.assertEqual(res.skip_reason, S.SKIP_NO_BREAKOUT)
        bars = or_then(D, 100.0, time(10, 55), 103.0)                        # closes 11:00: eligible
        self.assertIsNotNone(S.simulate_day(D, bars, self.F, P).signal)


class TestTradeManagement(unittest.TestCase):
    def sig(self, direction=LONG, s=2.0):
        return S.Signal(trade_date=D, direction=direction, signal_ts=datetime.combine(D, time(9, 50)),
                        signal_close=103.0, or_high=101.0, or_low=99.0, atr=10.0, cpr_top=100.3,
                        cpr_bottom=99.7, cpr_width_pct=0.6, day_open=100.0, prev_close=100.0,
                        stop_dist=s, _p=P)

    def bar(self, hhmm, o, h, l, c):
        return Bar(datetime.combine(D, hhmm), o, h, l, c)

    def test_target_and_stop_levels(self):
        bars = [self.bar(time(9, 50), 104.0, 104.5, 103.5, 104.0),
                self.bar(time(9, 55), 104.0, 107.2, 103.8, 107.0)]           # +1.5S = 107
        tr = S.simulate_trade(self.sig(), bars, P)
        self.assertEqual(tr.reason, S.EXIT_TARGET); self.assertAlmostEqual(tr.exit, 107.0)
        self.assertAlmostEqual(tr.r_gross, 1.5); self.assertAlmostEqual(tr.r_net(3.0), 1.5 - 1.5)

    def test_stop_first_when_both_hit(self):
        bars = [self.bar(time(9, 50), 104.0, 108.0, 101.5, 105.0)]            # stop 102 and target 107
        tr = S.simulate_trade(self.sig(), bars, P)
        self.assertEqual(tr.reason, S.EXIT_STOP); self.assertAlmostEqual(tr.exit, 102.0)
        self.assertAlmostEqual(tr.r_gross, -1.0)

    def test_breakeven_effective_next_bar(self):
        # bar 2 reaches +1S (106) then dips to entry: original stop still applies -> no exit
        bars = [self.bar(time(9, 50), 104.0, 104.5, 103.5, 104.0),
                self.bar(time(9, 55), 104.0, 106.1, 103.9, 105.0),
                self.bar(time(10, 0), 105.0, 105.5, 103.9, 104.5),            # touches entry: BE stop
                self.bar(time(10, 5), 104.5, 110.0, 104.4, 109.0)]
        tr = S.simulate_trade(self.sig(), bars, P)
        self.assertEqual(tr.reason, S.EXIT_BE_STOP)
        self.assertEqual(tr.exit_ts, datetime.combine(D, time(10, 0)))
        self.assertAlmostEqual(tr.exit, 104.0); self.assertAlmostEqual(tr.r_gross, 0.0)

    def test_time_exit(self):
        bars = [self.bar(time(9, 50), 104.0, 104.5, 103.5, 104.0)]
        t = time(9, 55)
        while t < time(15, 15):
            bars.append(self.bar(t, 104.0, 104.6, 103.6, 104.4)); t = S._add_minutes(t, 5)
        bars.append(self.bar(time(15, 15), 105.0, 105.2, 104.8, 105.1))
        tr = S.simulate_trade(self.sig(), bars, P)
        self.assertEqual(tr.reason, S.EXIT_TIME); self.assertAlmostEqual(tr.exit, 105.0)
        self.assertEqual(tr.exit_ts.time(), time(15, 15))

    def test_short_side_symmetry(self):
        bars = [self.bar(time(9, 50), 96.0, 96.5, 95.5, 96.0),
                self.bar(time(9, 55), 96.0, 96.2, 92.9, 93.0)]               # target 96-3 = 93
        tr = S.simulate_trade(self.sig(SHORT), bars, P)
        self.assertEqual(tr.reason, S.EXIT_TARGET); self.assertAlmostEqual(tr.r_gross, 1.5)

    def test_cost_in_r(self):
        tr = S.simulate_trade(self.sig(s=4.0), [self.bar(time(9, 50), 104.0, 110.5, 103.9, 110.0)], P)
        self.assertAlmostEqual(tr.r_net(0.0) - tr.r_net(3.0), 3.0 / 4.0)

    def test_drawdown_and_bootstrap(self):
        self.assertAlmostEqual(S.max_drawdown([1, -1, -1, 2]), 2.0)
        lo, hi = S.bootstrap_ci([0.5] * 50, n_boot=200)
        self.assertAlmostEqual(lo, 0.5); self.assertAlmostEqual(hi, 0.5)


class TestSpread(unittest.TestCase):
    QUOTES = {25000: (90.0, 92.0), 25150: (40.0, 41.0), 24850: (38.0, 39.5)}

    def test_long_ce_vertical_math(self):
        plan = S.plan_spread(LONG, 25012.0, date(2026, 7, 2), lambda k: self.QUOTES[k],
                             SpreadParams(width=150, lot=65))
        self.assertEqual((plan.right, plan.long_strike, plan.short_strike), ("CE", 25000, 25150))
        self.assertAlmostEqual(plan.debit, 92.0 - 40.0)                       # long ask - short bid
        self.assertAlmostEqual(plan.risk_inr, 0.4 * 52.0 * 65)
        self.assertAlmostEqual(plan.max_loss_inr, 52.0 * 65)
        self.assertAlmostEqual(plan.premium_stop, 52.0 * 0.6)
        self.assertTrue(plan.ok)

    def test_short_pe_and_cap(self):
        plan = S.plan_spread(SHORT, 24990.0, date(2026, 7, 2), lambda k: self.QUOTES[k],
                             SpreadParams(width=150, lot=65, risk_cap_inr=1000))
        self.assertEqual((plan.right, plan.short_strike), ("PE", 24850))
        self.assertFalse(plan.ok); self.assertIn("too expensive", plan.reason)

    def test_debit_cap(self):
        q = {25000: (150.0, 152.0), 25150: (40.0, 41.0)}
        plan = S.plan_spread(LONG, 25000.0, date(2026, 7, 2), lambda k: q[k],
                             SpreadParams(risk_cap_inr=1e9, max_debit=100))
        self.assertFalse(plan.ok)


class TestCalendar(unittest.TestCase):
    HOL = {date(2026, 7, 1)}

    def test_trading_day(self):
        self.assertFalse(S.is_trading_day(date(2026, 6, 27)))                 # Saturday
        self.assertFalse(S.is_trading_day(date(2026, 7, 1), self.HOL))
        self.assertTrue(S.is_trading_day(date(2026, 7, 2), self.HOL))

    def test_pick_expiry_rolls_on_expiry_day(self):
        listed = [date(2026, 6, 30), date(2026, 7, 7), date(2026, 7, 14)]
        self.assertEqual(S.pick_expiry(date(2026, 6, 30), listed, 1), date(2026, 7, 7))
        self.assertEqual(S.pick_expiry(date(2026, 6, 29), listed, 1), date(2026, 6, 30))
        # Mon 06-29 -> Tue 06-30 is 1 session; demanding 2 rolls to 07-07
        self.assertEqual(S.pick_expiry(date(2026, 6, 29), listed, 2), date(2026, 7, 7))
        self.assertEqual(S.sessions_until(date(2026, 6, 30), date(2026, 7, 2), self.HOL), 1)


class TestAlert(unittest.TestCase):
    def test_format_alert_snapshot(self):
        sig = S.Signal(trade_date=D, direction=LONG, signal_ts=datetime.combine(D, time(9, 50)),
                       signal_close=25012.0, or_high=25005.0, or_low=24930.0, atr=180.0,
                       cpr_top=24950.0, cpr_bottom=24930.0, cpr_width_pct=0.08, day_open=24960.0,
                       prev_close=24900.0, stop_dist=75.0, _p=P)
        plan = S.plan_spread(LONG, 25012.0, date(2026, 7, 2),
                             lambda k: {25000: (90.0, 92.0), 25150: (40.0, 41.0)}[k])
        text = S.format_alert(sig, 25015.0, plan, P, {"cpr": True, "gap": True, "or_min": True, "or_max": True})
        expected = "\n".join([
            "ORB-CPR-15 | NIFTY | LONG | 09:50",
            "OR  24930.00 - 25005.00 (rng 75.0)",
            "ATR 180.0  CPR 0.08%  gap +0.24%",
            "filters passed: cpr, gap, or_min, or_max",
            "",
            "entry ref 25015.00 (next bar open; chase <= 25033.00)",
            "stop  24940.00  (S = 75.0)",
            "target 25127.50  (+1.5R)",
            "BE trigger 25090.00  time exit 15:15",
            "",
            "BUY CE",
            "buy  25000 CE 02-Jul  bid/ask 90.00/92.00",
            "sell 25150 CE 02-Jul  bid/ask 40.00/41.00",
            "debit 52.00 x 65 = Rs 3,380",
            "premium stop 31.20  risk Rs 1,352",
            "max loss to expiry Rs 3,380  max profit Rs 6,370",
        ])
        self.assertEqual(text, expected)
        self.assertEqual(S.format_skip(D, S.SKIP_GAP), "ORB-CPR-15 | NIFTY | SKIP 25-Jun | gap_too_large")


if __name__ == "__main__":
    unittest.main()
