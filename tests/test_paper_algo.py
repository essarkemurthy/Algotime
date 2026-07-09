"""
Unit tests for paper_algo.AlgoPaperTrader — the signal-decision log and the
options auto-trade path. Pure/in-memory (no network, no Breeze).

Run:  python -m unittest tests.test_paper_algo
"""

import unittest
from datetime import date, datetime

from paper_engine import PaperTrader
from paper_algo import AlgoPaperTrader, AlgoConfig
from signals.detectors import Signal, LONG, SHORT, VWAP_TREND, EMA_X


TRADE_DATE = date(2026, 7, 7)


def mk_signal(symbol="TCS", strategy=VWAP_TREND, direction=LONG, *,
              trigger=100.0, vwap=99.0, atr=1.0, hour=10, minute=0):
    return Signal(
        symbol=symbol, strategy=strategy, direction=direction,
        ts=datetime(2026, 7, 7, hour, minute), trade_date=TRADE_DATE,
        trigger_price=trigger, vwap=vwap, rsi=60.0, vol_ratio=1.5, atr=atr,
    )


class FakeStore:
    """Captures paper-trade + decision writes for persistence assertions."""
    def __init__(self):
        self.trades = []
        self.decisions = []
    def insert_paper_trade(self, row):
        self.trades.append(row)
    def insert_signal_decision(self, row):
        self.decisions.append(row)


def make_algo(store=None, **cfg_kw):
    cfg_kw.setdefault("regime_filter", False)          # default: skip regime gating
    cfg_kw.setdefault("trade_intraday", True)          # default: intraday engine launched
    cfg = AlgoConfig(**cfg_kw)
    paper = PaperTrader(starting_capital=1_000_000.0)
    ltp = {}
    algo = AlgoPaperTrader(paper, ltp, cfg=cfg, store=store)
    return algo, paper, ltp


class DecisionLogTests(unittest.TestCase):
    def _last(self, algo):
        return algo._signals[0]   # newest first

    def test_skip_not_enabled(self):
        algo, _, ltp = make_algo()
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal(strategy=EMA_X))       # EMA_X off by default
        rec = self._last(algo)
        self.assertEqual(rec["decision"], "SKIPPED")
        self.assertEqual(rec["reason"], "not_enabled")
        self.assertEqual(len(algo._open), 0)

    def test_skip_no_atr(self):
        algo, _, ltp = make_algo()
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal(atr=float("nan")))
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("SKIPPED", "no_atr"))

    def test_cash_entry_executed(self):
        algo, paper, ltp = make_algo()
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal())
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("EXECUTED", "cash_entry"))
        self.assertEqual(rec["product"], "cash")
        self.assertIsNotNone(rec["entry_price"])
        self.assertIsNotNone(rec["exec_lag_sec"])
        self.assertEqual(len(algo._open), 1)
        pos = next(iter(algo._open.values()))
        # LONG: SL below entry, TP above entry (ATR-based).
        self.assertLess(pos.sl, pos.entry)
        self.assertGreater(pos.tp, pos.entry)

    def test_skip_filter(self):
        algo, _, ltp = make_algo(regime_filter=True)
        ltp["TCS"] = 100.0
        # LONG but trigger <= vwap → regime filter rejects.
        algo.on_signal(mk_signal(trigger=98.0, vwap=99.0))
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("SKIPPED", "filter"))

    def test_intraday_gate_off_skips_cash(self):
        algo, _, ltp = make_algo(trade_intraday=False)
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal())
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("SKIPPED", "intraday_algo_off"))
        self.assertEqual(len(algo._open), 0)

    def test_index_signal_options_off_skips(self):
        algo, _, ltp = make_algo(trade_options=False)   # options engine off
        ltp["NIFTY"] = 24000.0
        algo.on_signal(mk_signal(symbol="NIFTY"))
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("SKIPPED", "options_algo_off"))
        self.assertEqual(len(algo._open), 0)            # never traded as cash

    def test_duplicate_then_skipped(self):
        algo, _, ltp = make_algo()
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal())
        algo.on_signal(mk_signal())     # same (symbol, strategy) already open
        rec = self._last(algo)
        self.assertEqual((rec["decision"], rec["reason"]), ("SKIPPED", "duplicate"))
        self.assertEqual(len(algo._open), 1)


class OptionRoutingTests(unittest.TestCase):
    def test_routing_marks_pending_no_cash(self):
        algo, _, ltp = make_algo(trade_options=True)
        sig = mk_signal(symbol="NIFTY", direction=LONG)
        self.assertTrue(algo.wants_option(sig))
        algo.on_signal(sig)
        rec = algo._signals[0]
        self.assertEqual((rec["decision"], rec["reason"]), ("PENDING", "routed_option"))
        self.assertEqual(rec["product"], "options")
        self.assertEqual(len(algo._open), 0)          # no cash position opened

    def test_open_option_position_sizes_and_sets_sl_tp(self):
        algo, paper, ltp = make_algo(trade_options=True, capital_per_trade=100_000.0,
                                     option_sl_pct=0.30, option_tp_pct=0.50)
        sig = mk_signal(symbol="NIFTY", direction=LONG)
        algo.on_signal(sig)                            # PENDING
        contract = {"stock": "NIFTY", "right": "CE", "strike": 25000,
                    "expiry": "2026-07-10", "premium": 100.0, "exchange": "NFO"}
        ok = algo.open_option_position(sig, contract)
        self.assertTrue(ok)
        self.assertEqual(len(algo._open), 1)
        pos = next(iter(algo._open.values()))
        self.assertEqual(pos.product, "options")
        # lot 75, capital 100k, premium 100 → lots = 100000//(100*75)=13, qty=975
        self.assertEqual(pos.qty, 975)
        self.assertAlmostEqual(pos.sl, 70.0, places=2)   # 100 * (1-0.30)
        self.assertAlmostEqual(pos.tp, 150.0, places=2)  # 100 * (1+0.50)
        # the PENDING decision is finalised to EXECUTED
        rec = next(r for r in algo._signals if r["symbol"] == "NIFTY")
        self.assertEqual((rec["decision"], rec["reason"]), ("EXECUTED", "option_entry"))

    def test_option_tp_and_sl_pnl_sign(self):
        # TP: premium rises → long option profits.
        algo, paper, ltp = make_algo(trade_options=True)
        sig = mk_signal(symbol="NIFTY", direction=SHORT)   # SHORT → buy PE
        algo.on_signal(sig)
        contract = {"stock": "NIFTY", "right": "PE", "strike": 25000,
                    "expiry": "2026-07-10", "premium": 100.0, "exchange": "NFO"}
        algo.open_option_position(sig, contract)
        pos = next(iter(algo._open.values()))
        opt_sym = pos.symbol
        # premium jumps to TP → close as TP with positive P&L
        ltp[opt_sym] = pos.tp
        algo.on_tick(opt_sym, pos.tp)
        self.assertEqual(len(algo._open), 0)
        t = algo._closed[-1]
        self.assertEqual(t["reason"], "TP")
        self.assertEqual(t["product"], "options")
        self.assertGreater(t["pnl"], 0)          # long the premium, premium rose

    def test_option_sl_fires(self):
        algo, paper, ltp = make_algo(trade_options=True)
        sig = mk_signal(symbol="NIFTY", direction=LONG)
        algo.on_signal(sig)
        contract = {"stock": "NIFTY", "right": "CE", "strike": 25000,
                    "expiry": "2026-07-10", "premium": 100.0, "exchange": "NFO"}
        algo.open_option_position(sig, contract)
        pos = next(iter(algo._open.values()))
        ltp[pos.symbol] = pos.sl
        algo.on_tick(pos.symbol, pos.sl)
        t = algo._closed[-1]
        self.assertEqual(t["reason"], "SL")
        self.assertLess(t["pnl"], 0)

    def test_square_off_flattens_option(self):
        algo, paper, ltp = make_algo(trade_options=True)
        sig = mk_signal(symbol="NIFTY", direction=LONG)
        algo.on_signal(sig)
        contract = {"stock": "NIFTY", "right": "CE", "strike": 25000,
                    "expiry": "2026-07-10", "premium": 100.0, "exchange": "NFO"}
        algo.open_option_position(sig, contract)
        pos = next(iter(algo._open.values()))
        ltp[pos.symbol] = 90.0
        algo.square_off_all("SQUARE_OFF")
        self.assertEqual(len(algo._open), 0)
        self.assertEqual(algo._closed[-1]["reason"], "SQUARE_OFF")

    def test_snapshot_shape(self):
        algo, paper, ltp = make_algo()
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal())
        snap = algo.snapshot()
        for key in ("signals_log", "outcomes", "closed_trades", "open_positions", "config"):
            self.assertIn(key, snap)
        self.assertIn("trade_options", snap["config"])
        self.assertEqual(snap["open_positions"][0]["product"], "cash")


class PersistenceTests(unittest.TestCase):
    def test_cash_entry_and_exit_persist(self):
        store = FakeStore()
        algo, paper, ltp = make_algo(store=store)
        ltp["TCS"] = 100.0
        algo.on_signal(mk_signal())                     # EXECUTED cash_entry
        # a decision row was written (terminal EXECUTED)
        self.assertEqual(len(store.decisions), 1)
        d = store.decisions[0]
        self.assertEqual((d["decision"], d["reason"]), ("EXECUTED", "cash_entry"))
        self.assertIsNotNone(d["signal_ts"])
        self.assertIsNotNone(d["trade_date"])
        # close it → a paper_trades row is written
        pos = next(iter(algo._open.values()))
        ltp["TCS"] = pos.tp
        algo.on_tick("TCS", pos.tp)
        self.assertEqual(len(store.trades), 1)
        t = store.trades[0]
        self.assertEqual(t["source"], "Algo")
        self.assertEqual(t["product"], "cash")
        self.assertEqual(t["reason"], "TP")
        self.assertEqual(t["trade_date"], t["opened_ts"].date())
        self.assertGreater(t["pnl"], 0)

    def test_skipped_decision_persists_pending_does_not(self):
        store = FakeStore()
        algo, _, _ = make_algo(store=store, trade_options=True)
        # index signal with options armed → PENDING (not persisted)
        algo.on_signal(mk_signal(symbol="NIFTY"))
        self.assertEqual(len(store.decisions), 0)        # PENDING is transient
        # a skipped equity signal → persisted
        algo.on_signal(mk_signal(symbol="INFY", strategy=EMA_X))   # not_enabled
        self.assertEqual(len(store.decisions), 1)
        self.assertEqual(store.decisions[0]["decision"], "SKIPPED")


class PeriodRangeTests(unittest.TestCase):
    def test_period_math(self):
        from report_periods import period_range
        from datetime import date
        today = date(2026, 7, 9)
        # current FY (Jul → FY starts Apr of same year), capped at today
        f, t = period_range("fy", None, None, None, today=today)
        self.assertEqual((f, t), (date(2026, 4, 1), today))
        # explicit FY year → full Apr–Mar window
        f, t = period_range("fy", 2025, None, None, today=today)
        self.assertEqual((f, t), (date(2025, 4, 1), date(2026, 3, 31)))
        f, t = period_range("all", None, None, None, today=today)
        self.assertIsNone(f); self.assertIsNone(t)
        f, t = period_range("6m", None, None, None, today=today)
        self.assertEqual(f, date(2026, 1, 9))
        f, t = period_range(None, None, "2026-01-01", "2026-06-30", today=today)
        self.assertEqual((f, t), (date(2026, 1, 1), date(2026, 6, 30)))


if __name__ == "__main__":
    unittest.main()
