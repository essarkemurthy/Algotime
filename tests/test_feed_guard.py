"""Unit tests for feed_guard (derivative-tick detection, option key rebuild,
tick plausibility guard).  Run: python -m unittest tests.test_feed_guard"""

import unittest

import feed_guard as G

INDEX_NAMES = {"NIFTY 50", "NIFTY BANK", "NIFTY MIDCAP SELECT", "SENSEX"}


def index_tick(name="NIFTY 50", last=25900.0):
    return {"symbol": f"4.1!{name}", "last": last, "exchange": "NSE Equity", "stock_name": name}


def option_tick(last=170.5, name="NIFTY 50", right="Call", strike="25300", expiry="23-Nov-2026"):
    return {"symbol": "4.1!64456", "last": last, "exchange": "NSE Futures & Options", "stock_name": name,
            "product_type": "Options", "strike_price": strike, "right": right, "expiry_date": expiry}


class DerivativeDetection(unittest.TestCase):
    def test_index_tick_is_not_derivative(self):
        self.assertFalse(G.is_derivative_tick("4.1!NIFTY 50", index_tick(), INDEX_NAMES))

    def test_equity_numeric_token_is_not_derivative(self):
        t = {"symbol": "4.1!4963", "last": 1607.0, "exchange": "NSE Equity", "stock_name": "ICICI BANK LIMITED"}
        self.assertFalse(G.is_derivative_tick("4.1!4963", t, INDEX_NAMES))

    def test_option_tick_by_fields(self):
        self.assertTrue(G.is_derivative_tick("4.1!64456", option_tick(), INDEX_NAMES))

    def test_numeric_token_with_index_name_is_derivative(self):
        # 2026-11-19: the SDK gave no strike/right fields, only the underlying's name
        t = {"symbol": "4.1!64456", "last": 170.0, "stock_name": "NIFTY 50", "stock_code": ""}
        self.assertTrue(G.is_derivative_tick("4.1!64456", t, INDEX_NAMES))
        t["stock_name"] = "NIFTY BANK"
        self.assertTrue(G.is_derivative_tick("4.1!62462", t, INDEX_NAMES))

    def test_exchange_word_marks_derivative(self):
        t = {"symbol": "4.1!1", "last": 1.0, "exchange": "BSE Futures & Options", "stock_name": "SENSEX"}
        self.assertTrue(G.is_derivative_tick("4.1!1", t, ()))


class OptionKey(unittest.TestCase):
    def test_breeze_date_and_right_words(self):
        self.assertEqual(G.option_key_from_tick(option_tick(), "NIFTY"), "NIFTY_CE_25300_2026-11-23")
        self.assertEqual(G.option_key_from_tick(option_tick(right="Put", strike="25300.0"), "NIFTY"),
                         "NIFTY_PE_25300_2026-11-23")

    def test_iso_and_sdk_datetime(self):
        self.assertEqual(G.option_key_from_tick(option_tick(expiry="2026-11-23"), "NIFTY"), "NIFTY_CE_25300_2026-11-23")
        self.assertEqual(G.option_key_from_tick(option_tick(expiry="2026-11-23T06:00:00.000Z"), "NIFTY"),
                         "NIFTY_CE_25300_2026-11-23")

    def test_missing_parts_give_none(self):
        self.assertIsNone(G.option_key_from_tick({"stock_name": "NIFTY 50"}, "NIFTY"))
        self.assertIsNone(G.option_key_from_tick(option_tick(strike=""), "NIFTY"))
        self.assertIsNone(G.option_key_from_tick(option_tick(), ""))


class Guard(unittest.TestCase):
    def test_first_tick_and_normal_moves_accepted(self):
        g = G.TickGuard()
        self.assertEqual(g.check("NIFTY", 25900.0)[0], True)
        self.assertEqual(g.check("NIFTY", 25950.0)[0], True)
        self.assertEqual(g.check("NIFTY", 25000.0)[0], True)      # -3.7%, fine

    def test_option_premium_on_index_rejected_and_logged_once(self):
        g = G.TickGuard()
        g.check("NIFTY", 25900.0)
        ok, note = g.check("NIFTY", 170.0)
        self.assertFalse(ok); self.assertIn("rejected 170.00", note)
        ok, note = g.check("NIFTY", 171.0)
        self.assertFalse(ok); self.assertEqual(note, "")           # same episode: silent
        self.assertTrue(g.check("NIFTY", 25910.0)[0])               # real index ticks still flow

    def test_interleaved_outliers_never_confirm(self):
        g = G.TickGuard(confirm_after=5)
        g.check("NIFTY", 25900.0)
        for _ in range(20):
            self.assertFalse(g.check("NIFTY", 170.0)[0])
            self.assertTrue(g.check("NIFTY", 25905.0)[0])          # a good tick resets the outlier run

    def test_consistent_rebase_accepted_after_n(self):
        g = G.TickGuard(confirm_after=3)
        g.check("X", 100.0)
        self.assertFalse(g.check("X", 130.0)[0])
        self.assertFalse(g.check("X", 131.0)[0])
        ok, note = g.check("X", 130.5)
        self.assertTrue(ok); self.assertIn("accepted re-base", note)
        self.assertTrue(g.check("X", 131.0)[0])

    def test_disagreeing_outliers_restart_the_count(self):
        g = G.TickGuard(confirm_after=3)
        g.check("X", 100.0)
        g.check("X", 130.0); g.check("X", 131.0)
        self.assertFalse(g.check("X", 170.0)[0])                   # different outlier: run restarts
        self.assertFalse(g.check("X", 170.0)[0])
        self.assertTrue(g.check("X", 170.0)[0])

    def test_zero_or_negative_dropped(self):
        g = G.TickGuard()
        self.assertFalse(g.check("X", 0.0)[0])


if __name__ == "__main__":
    unittest.main()
