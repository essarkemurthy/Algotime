"""
Unit tests for live_orders.LiveOrderBridge (real-money follower of the options
paper engine). A fake Breeze API records orders; no network.

Run:  python -m unittest tests.test_live_orders
"""

import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import live_orders as L


def pos(symbol="NIFTY_CE_25300_2026-11-17", stock="NIFTY", exch="NFO", right="CE",
        strike=25300, expiry="2026-11-17", entry=200.0, product="options"):
    return SimpleNamespace(symbol=symbol, instrument=f"{stock} {strike} {right}", stock=stock,
                           exchange=exch, right=right, strike=strike, expiry=expiry,
                           entry=entry, product=product, qty=75)


class FakeApi:
    def __init__(self, reject=False, fill=201.5):
        self.orders = []
        self.reject = reject
        self.fill = fill

    def place_order(self, **kw):
        self.orders.append(kw)
        if self.reject:
            return {"Status": 500, "Success": None, "Error": "Insufficient funds"}
        return {"Status": 200, "Success": {"order_id": f"OID{len(self.orders)}"}, "Error": None}

    def get_order_detail(self, exchange_code, order_id):
        return {"Status": 200, "Success": [{"status": "Executed", "average_price": self.fill}]}


class FakeStore:
    def __init__(self): self.rows = []
    def insert_live_order(self, row): self.rows.append(row)


class Funds:
    """Callable funds getter with a mutable balance and a call counter."""
    def __init__(self, fno=100000.0, unallocated=0.0, blocked=0.0):
        self.fno, self.unallocated, self.blocked, self.calls = fno, unallocated, blocked, 0

    def __call__(self):
        self.calls += 1
        return {"allocated_fno": self.fno, "unallocated": self.unallocated, "blocked": self.blocked}


def bridge(api=None, env=True, funds=None, **cfg):
    cfg.setdefault("max_premium_inr", 1e9)       # sizing tests exercise the % rules, not the absolute cap
    b = L.LiveOrderBridge(api_getter=lambda: api, cfg=L.LiveConfig(fill_poll_sec=0, fill_poll_tries=1, **cfg),
                          store=FakeStore(), code_of=lambda s: {"BANKNIFTY": "CNXBAN", "SENSEX": "BSESEN"}.get(s, s),
                          funds_getter=funds if funds is not None else Funds())
    b.sync = True
    return b


class TestGates(unittest.TestCase):
    def test_env_gate(self):
        with mock.patch.dict(os.environ, {L.ENV_FLAG: "0"}):
            b = bridge()
            self.assertFalse(b.arm(L.CONFIRM_PHRASE)["ok"])
            self.assertFalse(b.active)

    def test_phrase_gate_and_dry_run_default(self):
        with mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}):
            b = bridge()
            self.assertFalse(b.arm("yes please")["ok"])
            self.assertTrue(b.arm(L.CONFIRM_PHRASE)["ok"])
            self.assertTrue(b.active); self.assertTrue(b.dry_run)
            b.arm(L.CONFIRM_PHRASE, dry_run=False)
            self.assertFalse(b.dry_run)
            b.disarm("manual")
            self.assertFalse(b.active)

    def test_not_armed_means_no_orders(self):
        api = FakeApi()
        with mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}):
            b = bridge(api)
            b.on_paper_entry(pos(), 200.0)
            self.assertEqual(api.orders, []); self.assertEqual(b.open, {})


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}); self.env.start()
        self.api = FakeApi()
        self.b = bridge(self.api, funds=Funds(fno=300000))   # 2% risk = 6000; 1 lot NIFTY @200 risks 4500
        self.b.arm(L.CONFIRM_PHRASE, dry_run=True)

    def tearDown(self): self.env.stop()

    def test_entry_exit_journal_and_pnl(self):
        p = pos()
        self.b.on_paper_entry(p, 200.0)
        self.assertEqual(self.api.orders, [])                       # nothing sent
        self.assertIn(p.symbol, self.b.open)
        self.assertEqual(self.b.open[p.symbol].qty, 75)
        self.b.on_paper_exit(p, 230.0, "TP")
        self.assertNotIn(p.symbol, self.b.open)
        self.assertAlmostEqual(self.b.realised_pnl, 30.0 * 75)
        acts = [r["action"] for r in self.b.store.rows]
        self.assertEqual(acts, ["buy", "sell"])
        self.assertTrue(all(r["dry_run"] for r in self.b.store.rows))
        self.assertIn("1 lot", self.b.store.rows[0]["reason"])


class TestSizing(unittest.TestCase):
    """lots = min(max_lots, risk, entry exposure, total exposure, cash, premium cap)."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}); self.env.start()

    def tearDown(self): self.env.stop()

    def test_risk_budget_binds(self):
        # capital 1,00,000 · risk 2% = 2,000 · NIFTY @100: premium/lot 7,500, risk/lot 2,250 → 0 lots
        b = bridge(FakeApi(), funds=Funds(fno=100000)); b.arm(L.CONFIRM_PHRASE)
        sz = b.size("NIFTY", 100.0)
        self.assertEqual(sz.lots, 0); self.assertIn("risk 2%", sz.reason); self.assertIn("one lot needs", sz.reason)
        # SENSEX @100: premium/lot 2,000, risk/lot 600 → risk allows 3, entry 25% = 25,000 allows 12 → 3 lots
        sz = b.size("SENSEX", 100.0)
        self.assertEqual((sz.lots, sz.qty), (3, 60)); self.assertIn("risk 2%", sz.reason)

    def test_exposure_and_max_lots_bind(self):
        # capital 10,00,000 · risk 2% = 20,000 · SENSEX @100: risk/lot 600 → 33; entry 25% = 2,50,000 → 125; max_lots 5
        b = bridge(FakeApi(), funds=Funds(fno=1000000), max_lots=5); b.arm(L.CONFIRM_PHRASE)
        sz = b.size("SENSEX", 100.0)
        self.assertEqual(sz.lots, 5); self.assertIn("max_lots", sz.reason)
        # exposure binds when the premium is large: @5000 premium/lot 1,00,000 → entry 25% allows 2, risk 20,000/30,000 → 0
        b2 = bridge(FakeApi(), funds=Funds(fno=1000000), max_lots=50, risk_pct=100); b2.arm(L.CONFIRM_PHRASE)
        sz = b2.size("SENSEX", 5000.0)
        self.assertEqual(sz.lots, 2); self.assertIn("entry 25%", sz.reason)

    def test_unknown_funds_means_no_trade(self):
        api = FakeApi()
        b = bridge(api, funds=lambda: None); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(), 200.0)
        self.assertEqual(api.orders, []); self.assertIn("capital unknown", b.store.rows[-1]["reason"])

    def test_blocked_margin_is_not_capital(self):
        # the account as seen on 2026-11-12: F&O 10,214.75 + unallocated 1,461.65 - blocked 3,774.84
        b = bridge(FakeApi(), funds=Funds(fno=10214.75, unallocated=1461.65, blocked=3774.84)); b.arm(L.CONFIRM_PHRASE)
        self.assertAlmostEqual(b.capital(), 7901.56)
        sz = b.size("SENSEX", 300.0)                                 # risk 158 vs 1,800 per lot -> nothing
        self.assertEqual(sz.lots, 0); self.assertIn("one lot needs", sz.reason)

    def test_capital_override_caps_funds(self):
        b = bridge(FakeApi(), funds=Funds(fno=1000000), capital_override_inr=20000); b.arm(L.CONFIRM_PHRASE)
        self.assertEqual(b.capital(), 20000)
        self.assertEqual(b.size("SENSEX", 100.0).lots, 0)          # risk 400 < 600 per lot

    def test_fixed_lots_still_cash_checked(self):
        b = bridge(FakeApi(), funds=Funds(fno=5000), lots=3); b.arm(L.CONFIRM_PHRASE)
        sz = b.size("SENSEX", 100.0)                                 # 3 lots = 6,000 > cash 4,750 → 2
        self.assertEqual(sz.lots, 2); self.assertIn("cash", sz.reason)
        b2 = bridge(FakeApi(), funds=Funds(fno=50000), lots=3); b2.arm(L.CONFIRM_PHRASE)
        self.assertEqual(b2.size("SENSEX", 100.0).lots, 3)

    def test_dry_run_open_premium_reduces_cash_and_total_room(self):
        # capital 10,000 · total 50% = 5,000 · SENSEX @100 (2,000/lot): risk 200/600 → 0 unless risk_pct high
        b = bridge(FakeApi(), funds=Funds(fno=10000), risk_pct=100, max_open=3, max_lots=10); b.arm(L.CONFIRM_PHRASE)
        self.assertEqual(b.size("SENSEX", 100.0).lots, 1)           # entry 25% = 2,500 → 1 lot
        b.on_paper_entry(pos(symbol="SENSEX_CE_1", stock="SENSEX", exch="BFO", entry=100.0), 100.0)
        sz = b.size("SENSEX", 100.0)                                 # room 5,000-2,000 = 3,000 → 1; entry → 1
        self.assertEqual(sz.lots, 1)
        b.on_paper_entry(pos(symbol="SENSEX_CE_2", stock="SENSEX", exch="BFO", entry=100.0), 100.0)
        sz = b.size("SENSEX", 100.0)                                 # room 1,000 → 0
        self.assertEqual(sz.lots, 0); self.assertIn("total 50%", sz.reason)

    def test_funds_cached_then_refreshed_after_real_fill(self):
        f = Funds(fno=300000)
        b = bridge(FakeApi(), funds=f); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        n = f.calls
        b.size("NIFTY", 200.0); b.size("NIFTY", 200.0)
        self.assertEqual(f.calls, n)                                 # served from the 60 s cache
        b.on_paper_entry(pos(), 200.0)
        b.size("NIFTY", 200.0)
        self.assertEqual(f.calls, n + 1)                             # premium debited → re-read


class TestReal(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}); self.env.start()

    def tearDown(self): self.env.stop()

    def test_real_order_uses_broker_codes_and_fill(self):
        api = FakeApi(fill=205.0)
        b = bridge(api, funds=Funds(fno=500000)); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(symbol="BANKNIFTY_PE_61000_2026-11-23", stock="BANKNIFTY", right="PE", strike=61000,
                expiry="2026-11-23", entry=400.0)
        b.on_paper_entry(p, 400.0)                                   # risk 10,000 / (400*35*0.3=4,200) → 2 lots
        self.assertEqual(len(api.orders), 1)
        o = api.orders[0]
        self.assertEqual((o["stock_code"], o["exchange_code"], o["action"], o["right"], o["strike_price"], o["quantity"]),
                         ("CNXBAN", "NFO", "buy", "put", "61000", "70"))
        self.assertEqual(o["expiry_date"], "2026-11-23T06:00:00.000Z")
        self.assertAlmostEqual(b.open[p.symbol].entry, 205.0)       # broker fill, not paper price
        self.assertEqual(b.open[p.symbol].lots, 2)
        b.on_paper_exit(p, 380.0, "SL")
        self.assertEqual(api.orders[1]["action"], "sell")
        self.assertEqual(api.orders[1]["quantity"], "70")
        self.assertAlmostEqual(b.realised_pnl, (205.0 - 205.0) * 70)  # fake fills both at 205

    def test_sensex_routes_to_bfo(self):
        api = FakeApi()
        b = bridge(api, funds=Funds(fno=100000)); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(symbol="SENSEX_CE_81500_2026-11-12", stock="SENSEX", exch="BFO", right="CE",
                strike=81500, expiry="2026-11-12", entry=300.0)
        b.on_paper_entry(p, 300.0)                                   # risk 2,000 / (300*20*0.3=1,800) → 1 lot
        self.assertEqual((api.orders[0]["stock_code"], api.orders[0]["exchange_code"], api.orders[0]["quantity"]),
                         ("BSESEN", "BFO", "20"))

    def test_rejected_order_is_skipped_not_opened(self):
        api = FakeApi(reject=True)
        b = bridge(api, funds=Funds(fno=300000)); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(), 200.0)
        self.assertEqual(b.open, {})
        self.assertEqual(b.store.rows[-1]["status"], "SKIPPED")
        self.assertIn("Insufficient", b.store.rows[-1]["reason"])

    def test_limits(self):
        api = FakeApi()
        b = bridge(api, funds=Funds(fno=300000), max_open=1, max_premium_inr=10000); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(entry=200.0), 200.0)                   # 200*75 = 15000 > premium cap → 0 lots
        self.assertEqual(b.open, {}); self.assertIn("premium cap", b.store.rows[-1]["reason"])
        b.on_paper_entry(pos(symbol="NIFTY_PE_25000_2026-11-17", right="PE", strike=25000, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 1)
        b.on_paper_entry(pos(symbol="NIFTY_CE_25400_2026-11-17", strike=25400, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 1); self.assertIn("max_open", b.store.rows[-1]["reason"])
        b.on_paper_entry(pos(symbol="X_CE_1_2026-11-17", stock="XYZ", entry=10.0), 10.0)
        self.assertIn("not allowed", b.store.rows[-1]["reason"])

    def test_max_trades_per_day(self):
        api = FakeApi()
        b = bridge(api, funds=Funds(fno=300000), max_open=5, max_trades_per_day=2); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        for i in range(3):
            b.on_paper_entry(pos(symbol=f"NIFTY_CE_{i}", strike=25000 + i, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 2); self.assertIn("max_trades_per_day", b.store.rows[-1]["reason"])

    def test_daily_loss_cap_disarms_absolute(self):
        api = FakeApi(fill=100.0)
        b = bridge(api, funds=Funds(fno=300000), daily_loss_cap_inr=1000, daily_loss_pct=100); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(entry=100.0)
        b.on_paper_entry(p, 100.0)                                   # risk 6,000 / 2,250 → 2 lots = 150
        api.fill = 80.0                                             # exit fills at 80: -20*150 = -3000
        b.on_paper_exit(p, 80.0, "SL")
        self.assertAlmostEqual(b.realised_pnl, -3000.0)
        self.assertFalse(b.active); self.assertEqual(b.disarm_reason, "daily loss cap")

    def test_daily_loss_cap_relative_is_lower(self):
        # capital 50,000 · 3% = 1,500 < absolute 3,000 → cap 1,500
        api = FakeApi(fill=100.0)
        b = bridge(api, funds=Funds(fno=50000), risk_pct=10); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        self.assertAlmostEqual(b.loss_cap(), 1500.0)
        p = pos(stock="SENSEX", exch="BFO", symbol="SENSEX_CE_1", entry=100.0)
        b.on_paper_entry(p, 100.0)                                   # risk 5,000/600 → 8 → max_lots 5 → 100 qty
        api.fill = 80.0                                             # -20*100 = -2000 ≥ cap 1,500
        b.on_paper_exit(p, 80.0, "SL")
        self.assertFalse(b.active); self.assertEqual(b.disarm_reason, "daily loss cap")

    def test_consecutive_losses_disarm(self):
        api = FakeApi(fill=100.0)
        b = bridge(api, funds=Funds(fno=10000000), max_consec_losses=2, daily_loss_cap_inr=1e9, daily_loss_pct=100,
                   max_open=3, max_lots=1); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p1 = pos(symbol="S1", entry=100.0); p2 = pos(symbol="S2", strike=25400, entry=100.0)
        b.on_paper_entry(p1, 100.0); b.on_paper_entry(p2, 100.0)
        api.fill = 99.0
        b.on_paper_exit(p1, 99.0, "SL")
        self.assertTrue(b.active); self.assertEqual(b.consec_losses, 1)
        b.on_paper_exit(p2, 99.0, "SL")
        self.assertFalse(b.active); self.assertEqual(b.disarm_reason, "2 consecutive losses")

    def test_kill_flattens_and_disarms(self):
        api = FakeApi()
        b = bridge(api, funds=Funds(fno=300000), max_open=2, max_lots=1); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(entry=100.0), 100.0)
        b.on_paper_entry(pos(symbol="NIFTY_PE_25000_2026-11-17", right="PE", strike=25000, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 2)
        b.kill()
        self.assertEqual(b.open, {}); self.assertTrue(b.killed); self.assertFalse(b.active)
        self.assertEqual([o["action"] for o in api.orders], ["buy", "buy", "sell", "sell"])


if __name__ == "__main__":
    unittest.main()
