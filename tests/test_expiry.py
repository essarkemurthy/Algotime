"""Regression test for the NSE Tuesday-expiry fix (was last-Thursday).

Verifies the computed expiries match the real Breeze contracts for a known
date (the security master listed 30-Jun / 28-Jul / 25-Aug 2026, all Tuesdays).
"""
import unittest
from datetime import date

from trade_engine.symbols import (expiry_candidates_after, monthly_expiries,
                                  master_expiry, nearest_monthly_expiry,
                                  nearest_weekly_expiry, parse_breeze_expiry)

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


    # Breeze quotes expiries as '09-Nov-2026'; ISO is accepted for cached values.
    def test_parse_breeze_expiry(self):
        self.assertEqual(parse_breeze_expiry("09-Nov-2026"), date(2026, 11, 9))
        self.assertEqual(parse_breeze_expiry("2026-11-17T06:00:00.000Z"), date(2026, 11, 17))
        self.assertIsNone(parse_breeze_expiry(""))
        self.assertIsNone(parse_breeze_expiry(None))
        self.assertIsNone(parse_breeze_expiry("junk"))

    # Tue 2026-11-10 is a holiday so that week's NIFTY expiry was Mon 11-09; the
    # roll candidates must still reach the regular 11-17 weekly and 11-24 monthly.
    def test_roll_candidates_after_holiday_shifted_expiry(self):
        cands = expiry_candidates_after(date(2026, 11, 9))
        self.assertEqual(cands, [date(2026, 11, 10), date(2026, 11, 17), date(2026, 11, 24)])
        for c in cands:
            self.assertGreater(c, date(2026, 11, 9))

    def test_roll_candidates_after_monthly(self):
        self.assertEqual(expiry_candidates_after(date(2026, 11, 24)),
                         [date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 29)])


    # The security-master key wants '17-Nov-2026'; ISO (what REST calls use) must be converted.
    def test_master_expiry_formats(self):
        self.assertEqual(master_expiry("2026-11-17T06:00:00.000Z"), "17-Nov-2026")
        self.assertEqual(master_expiry("2026-11-17"), "17-Nov-2026")
        self.assertEqual(master_expiry("17-Nov-2026"), "17-Nov-2026")
        self.assertEqual(master_expiry(""), "")


if __name__ == "__main__":
    unittest.main()
