"""Regression test for the NSE Tuesday-expiry fix (was last-Thursday).

Verifies the computed expiries match the real Breeze contracts for a known
date (the security master listed 30-Jun / 28-Jul / 25-Aug 2026, all Tuesdays).
"""
import unittest
from datetime import date

from trade_engine.symbols import (monthly_expiries, nearest_monthly_expiry,
                                  nearest_weekly_expiry)

TUESDAY = 1


class TestExpiry(unittest.TestCase):
    def test_monthly_matches_master(self):
        exps = monthly_expiries(3, date(2026, 6, 26))
        self.assertEqual(exps, [date(2026, 6, 30), date(2026, 7, 28), date(2026, 8, 25)])

    def test_all_expiries_are_tuesdays(self):
        for e in monthly_expiries(6, date(2026, 6, 26)):
            self.assertEqual(e.weekday(), TUESDAY, f"{e} is not a Tuesday")

    def test_nearest_weekly_is_tuesday(self):
        wk = nearest_weekly_expiry(date(2026, 6, 26))   # Fri → next Tue
        self.assertEqual(wk, date(2026, 6, 30))
        self.assertEqual(wk.weekday(), TUESDAY)

    def test_nearest_monthly_not_in_past(self):
        self.assertGreaterEqual(nearest_monthly_expiry(date(2026, 6, 26)), date(2026, 6, 26))


if __name__ == "__main__":
    unittest.main()
