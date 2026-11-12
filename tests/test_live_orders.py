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


def bridge(api=None, env=True, **cfg):
    b = L.LiveOrderBridge(api_getter=lambda: api, cfg=L.LiveConfig(fill_poll_sec=0, fill_poll_tries=1, **cfg),
                          store=FakeStore(), code_of=lambda s: {"BANKNIFTY": "CNXBAN", "SENSEX": "BSESEN"}.get(s, s))
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
        self.b = bridge(self.api)
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


class TestReal(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {L.ENV_FLAG: "1"}); self.env.start()

    def tearDown(self): self.env.stop()

    def test_real_order_uses_broker_codes_and_fill(self):
        api = FakeApi(fill=205.0)
        b = bridge(api); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(symbol="BANKNIFTY_PE_61000_2026-11-23", stock="BANKNIFTY", right="PE", strike=61000,
                expiry="2026-11-23", entry=400.0)
        b.on_paper_entry(p, 400.0)
        self.assertEqual(len(api.orders), 1)
        o = api.orders[0]
        self.assertEqual((o["stock_code"], o["exchange_code"], o["action"], o["right"], o["strike_price"], o["quantity"]),
                         ("CNXBAN", "NFO", "buy", "put", "61000", "35"))
        self.assertEqual(o["expiry_date"], "2026-11-23T06:00:00.000Z")
        self.assertAlmostEqual(b.open[p.symbol].entry, 205.0)       # broker fill, not paper price
        b.on_paper_exit(p, 380.0, "SL")
        self.assertEqual(api.orders[1]["action"], "sell")
        self.assertAlmostEqual(b.realised_pnl, (205.0 - 205.0) * 35)  # fake fills both at 205

    def test_sensex_routes_to_bfo(self):
        api = FakeApi()
        b = bridge(api); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(symbol="SENSEX_CE_81500_2026-11-12", stock="SENSEX", exch="BFO", right="CE",
                strike=81500, expiry="2026-11-12", entry=300.0)
        b.on_paper_entry(p, 300.0)
        self.assertEqual((api.orders[0]["stock_code"], api.orders[0]["exchange_code"], api.orders[0]["quantity"]),
                         ("BSESEN", "BFO", "20"))

    def test_rejected_order_is_skipped_not_opened(self):
        api = FakeApi(reject=True)
        b = bridge(api); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(), 200.0)
        self.assertEqual(b.open, {})
        self.assertEqual(b.store.rows[-1]["status"], "SKIPPED")
        self.assertIn("Insufficient", b.store.rows[-1]["reason"])

    def test_limits(self):
        api = FakeApi()
        b = bridge(api, max_open=1, max_premium_inr=10000); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(entry=200.0), 200.0)                   # 200*75 = 15000 > cap
        self.assertEqual(b.open, {}); self.assertIn("premium", b.store.rows[-1]["reason"])
        b.on_paper_entry(pos(symbol="NIFTY_PE_25000_2026-11-17", right="PE", strike=25000, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 1)
        b.on_paper_entry(pos(symbol="NIFTY_CE_25400_2026-11-17", strike=25400, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 1); self.assertIn("max_open", b.store.rows[-1]["reason"])
        b.on_paper_entry(pos(symbol="X_CE_1_2026-11-17", stock="XYZ", entry=10.0), 10.0)
        self.assertIn("not allowed", b.store.rows[-1]["reason"])

    def test_daily_loss_cap_disarms(self):
        api = FakeApi(fill=100.0)
        b = bridge(api, daily_loss_cap_inr=1000); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        p = pos(entry=100.0)
        b.on_paper_entry(p, 100.0)
        api.fill = 80.0                                             # exit fills at 80: -20*75 = -1500
        b.on_paper_exit(p, 80.0, "SL")
        self.assertAlmostEqual(b.realised_pnl, -1500.0)
        self.assertFalse(b.active); self.assertEqual(b.disarm_reason, "daily loss cap")

    def test_kill_flattens_and_disarms(self):
        api = FakeApi()
        b = bridge(api, max_open=2); b.arm(L.CONFIRM_PHRASE, dry_run=False)
        b.on_paper_entry(pos(entry=100.0), 100.0)
        b.on_paper_entry(pos(symbol="NIFTY_PE_25000_2026-11-17", right="PE", strike=25000, entry=100.0), 100.0)
        self.assertEqual(len(b.open), 2)
        b.kill()
        self.assertEqual(b.open, {}); self.assertTrue(b.killed); self.assertFalse(b.active)
        self.assertEqual([o["action"] for o in api.orders], ["buy", "buy", "sell", "sell"])


if __name__ == "__main__":
    unittest.main()
