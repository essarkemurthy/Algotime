"""chat_agent: snapshot trimming, message assembly and the Claude call (faked)."""
import json
import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chat_agent as C  # noqa: E402


def _algo():
    return {
        "config": {"capital_per_trade": 50000, "trade_options": True},
        "strategies": [{"strategy": "VWAP_TREND", "enabled": True, "open": 1, "closed": 2,
                        "wins": 1, "pnl": -340.0},
                       {"strategy": "ORB", "enabled": False, "open": 0, "closed": 0, "wins": 0,
                        "pnl": 0.0}],
        "open_positions": [{"symbol": "NIFTY_CE_25500_2026-12-01", "strategy": "VWAP_TREND",
                            "direction": "LONG", "product": "options", "qty": 65, "entry": 120.0,
                            "sl": 84.0, "tp": 180.0, "ltp": 131.5, "upnl": 747.5,
                            "opened_at": "10:12:00"}],
        "closed_trades": [{"pnl": -340.0}] * 2,
        "signals_log": [{"ts": "10:11:58", "strategy": "VWAP_TREND", "symbol": "NIFTY",
                         "direction": "LONG", "status": "TAKEN", "secret_blob": "x" * 5000}] * 30,
        "outcomes": {"TP": 1, "SL": 1, "SQUARE_OFF": 0, "OTHER": 0},
        "realised_pnl": -340.0,
        "open_count": 1,
    }


def _paper():
    return {"starting_capital": 500000, "cash": 480000.0, "invested": 20000.0, "equity": 500747.5,
            "unrealised_pnl": 747.5, "realised_pnl": 0.0, "total_pnl": 747.5, "pnl_pct": 0.15,
            "open_positions": [{"symbol": "RELIANCE", "direction": "buy", "qty": 10,
                                "avg_price": 1400.0, "ltp": 1410.0, "unrealised": 100.0}],
            "closed_positions": [{"id": 1}] * 500, "orders": [{"id": 1}] * 900}


class SnapshotTests(unittest.TestCase):
    def test_trims_heavy_fields_and_keeps_positions(self):
        snap = C.build_snapshot(
            status={"connected": True, "algo_running": True,
                    "candle_sync": {"last_run": "2026-11-26T10:47:22", "last_result": "ok"}},
            funds={"allocated_fno": 10214.75},
            ltp={"NIFTY": 25500.5, "RELIANCE": 1410.0, "NIFTY_CE_25500_2026-12-01": 131.5,
                 "TCS": 3000.0},
            prev_close={"NIFTY": 25400.0},
            algo=_algo(), paper_summary=_paper(),
            manual_positions={"total_pnl": 0, "positions": []},
            live={"env_enabled": False, "armed": False, "dry_run": True, "open": [],
                  "orders": [{"x": 1}] * 50, "confirm_phrase": "I APPROVE LIVE ORDERS"},
            trades_today=[{"closed_ts": datetime(2026, 11, 26, 10, 40), "strategy": "VWAP_TREND",
                           "product": "options", "pnl": -340.0, "reason": "SL",
                           "huge": "y" * 10000}],
            alltime={"total": {"trades": 939, "pnl": -138293.0}},
            now=datetime(2026, 11, 26, 10, 50, 0),
        )
        body = json.dumps(snap, default=str)
        self.assertNotIn("secret_blob", body)          # signals trimmed to known keys
        self.assertNotIn("closed_positions", body)     # paper history not shipped
        self.assertNotIn("confirm_phrase", body)       # arming phrase never leaves the server
        self.assertNotIn("huge", body)
        self.assertEqual(snap["indices"]["NIFTY"]["change_pct"], 0.4)
        self.assertEqual(snap["held_symbol_ltp"], {"NIFTY_CE_25500_2026-12-01": 131.5,
                                                   "RELIANCE": 1410.0})
        self.assertEqual(snap["paper_algo"]["enabled_strategies"], ["VWAP_TREND"])
        self.assertEqual(len(snap["paper_algo"]["recent_signals"]), C.MAX_SIGNALS)
        self.assertEqual(snap["paper_manual"]["unrealised_pnl"], 747.5)
        self.assertEqual(snap["market_session"], "open")
        self.assertEqual(snap["closed_today"][0]["closed_ts"], "2026-11-26T10:40:00")
        self.assertLess(len(body), 6000)

    def test_handles_empty_state(self):
        snap = C.build_snapshot(now=datetime(2026, 11, 28, 12, 0))   # a Saturday
        self.assertEqual(snap["market_session"], "closed")
        self.assertIsNone(snap["paper_algo"])
        self.assertEqual(snap["indices"], {})

    def test_alltime_totals(self):
        rows = [{"product": "options", "pnl": -100.0}, {"product": "options", "pnl": 40.0},
                {"product": "intraday", "pnl": 10.0}]
        t = C.alltime_totals(rows)
        self.assertEqual(t["total"], {"trades": 3, "pnl": -50.0})
        self.assertEqual(t["by_product"]["options"]["win_rate_pct"], 50.0)


class MessageTests(unittest.TestCase):
    def test_snapshot_only_in_last_user_turn_and_history_cleaned(self):
        hist = [{"role": "assistant", "content": "orphan"},     # dropped: must start with user
                {"role": "user", "content": "hi"},
                {"role": "user", "content": "again"},           # merged into previous user turn
                {"role": "assistant", "content": "hello"},
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "dangling"}]        # dropped: new question follows
        msgs = C.build_messages(hist, "what is open?", {"k": 1})
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], "hi\nagain")
        self.assertIn("<situation>", msgs[-1]["content"])
        self.assertNotIn("<situation>", msgs[0]["content"])
        self.assertTrue(msgs[-1]["content"].startswith("what is open?"))

    def test_history_capped(self):
        hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(60)]
        msgs = C.build_messages(hist, "q", {})
        self.assertLessEqual(len(msgs), C.MAX_HISTORY_TURNS + 1)

    def test_empty_question_rejected(self):
        with self.assertRaises(ValueError):
            C.build_messages([], "   ", {})


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(*responses):
    fm = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=fm)), fm


def _resp(text="answer", stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)],
                           stop_reason=stop, stop_details=None, model=model,
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=80,
                                                 cache_read_input_tokens=900))


class AskTests(unittest.TestCase):
    def test_request_shape(self):
        client, fm = _client(_resp("You hold one NIFTY call."))
        out = C.ask(client, [], "what is my position?", {"indices": {}})
        self.assertEqual(out["answer"], "You hold one NIFTY call.")
        self.assertEqual(out["usage"]["cache_read"], 900)
        kw = fm.calls[0]
        self.assertEqual(kw["model"], C.MODEL)
        self.assertEqual(kw["output_config"], {"effort": C.EFFORT})
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(kw["extra_body"], {"fallbacks": "default"})
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["thinking"], {"type": "adaptive"})   # no budget_tokens on Opus 5.5
        self.assertNotIn("temperature", kw)

    def test_retries_without_fallback_when_beta_rejected(self):
        client, fm = _client(RuntimeError("Unexpected value(s) for the anthropic-beta header: "
                                          "server-side-fallback-2026-07-01"),
                             _resp("ok"))
        out = C.ask(client, [], "q", {})
        self.assertEqual(out["answer"], "ok")
        self.assertEqual(len(fm.calls), 2)
        self.assertNotIn("extra_body", fm.calls[1])

    def test_other_errors_propagate(self):
        client, _ = _client(RuntimeError("connection reset"))
        with self.assertRaises(RuntimeError):
            C.ask(client, [], "q", {})

    def test_refusal_and_truncation(self):
        client, _ = _client(_resp("", stop="refusal"))
        self.assertIn("can't answer", C.ask(client, [], "q", {})["answer"])
        client, _ = _client(_resp("partial", stop="max_tokens"))
        self.assertIn("token limit", C.ask(client, [], "q", {})["answer"])


def _daily(n=70, start=25000.0):
    import random
    from datetime import timedelta
    rnd = random.Random(7)
    rows, p, t = [], start, datetime(2026, 8, 1)
    while len(rows) < n:
        t += timedelta(days=1)
        if t.weekday() > 4:
            continue
        o = p
        c = p + rnd.uniform(-150, 150)
        rows.append({"ts": t, "open": o, "high": max(o, c) + rnd.uniform(0, 80),
                     "low": min(o, c) - rnd.uniform(0, 80), "close": c, "volume": 0})
        p = c
    return rows


def _intraday(day, start, bars, step=5):
    from datetime import timedelta
    rows, p = [], start
    t = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15)
    for k in range(bars):
        c = p + (3 if k % 2 else -2)
        rows.append({"ts": t, "open": p, "high": max(p, c) + 4, "low": min(p, c) - 4, "close": c})
        p, t = c, t + timedelta(minutes=step)
    return rows


class MarketContextTests(unittest.TestCase):
    def setUp(self):
        from datetime import timedelta
        self.daily = _daily()
        self.now = (self.daily[-1]["ts"] + timedelta(days=1)).replace(hour=10, minute=20)
        prev = self.daily[-1]
        self.prev = prev
        last_close = prev["close"]
        self.intraday = (_intraday(self.now.date() - timedelta(days=1), last_close - 50, 75)
                         + _intraday(self.now.date(), last_close + 40, 13))
        self.chain = {"expiry": self.now.date().isoformat(), "atm": 25000, "pcr": 0.85, "spot": 25010.0,
                      "lot_size": 65,
                      "rows": [{"strike": s, "ce": {"ltp": 100.0, "oi": 5000 if s == 25200 else 1000, "iv": 12.1},
                                "pe": {"ltp": 90.0, "oi": 7000 if s == 24800 else 900, "iv": 13.0}}
                               for s in range(24500, 25550, 50)]}

    def test_levels_match_pivot_arithmetic_and_today_is_derived_from_intraday(self):
        h, l, c = self.prev["high"], self.prev["low"], self.prev["close"]
        ref = round(c + 5.0, 2)
        m = C.market_context(daily=self.daily, intraday=self.intraday, chain=self.chain,
                             vix={"value": 13.2, "ts": self.now}, ltp=ref, now=self.now)
        p = (h + l + c) / 3
        lv = m["levels_from_prev_session"]
        self.assertAlmostEqual(lv["P"], round(p, 2), places=2)
        self.assertAlmostEqual(lv["R1"], round(2 * p - l, 2), places=2)
        self.assertAlmostEqual(lv["S1"], round(2 * p - h, 2), places=2)
        self.assertAlmostEqual(lv["H4"], round(c + 1.1 * (h - l) / 2, 2), places=2)
        self.assertEqual(m["daily"]["prev_session"]["date"], self.prev["ts"].date().isoformat())
        self.assertEqual(len(m["daily"]["recent_sessions"]), C.DAILY_ROWS_KEPT)
        self.assertIsNotNone(m["daily"]["atr14"])
        self.assertIsNotNone(m["daily"]["adx14"])
        self.assertIsNotNone(m["daily"]["sma50"])
        it = m["intraday"]
        self.assertEqual(it["bars_today"], 13)
        self.assertAlmostEqual(it["today_open"], round(c + 40, 2), places=2)
        orb = it["opening_range_0915_0930"]
        today = [b for b in self.intraday if b["ts"].date() == self.now.date()][:3]
        self.assertAlmostEqual(orb["high"], round(max(b["high"] for b in today), 2), places=2)
        self.assertAlmostEqual(orb["low"], round(min(b["low"] for b in today), 2), places=2)
        self.assertAlmostEqual(it["gap_points"], round(40.0, 2), places=1)
        self.assertEqual(len(it["last_bars"]), C.INTRADAY_BARS_KEPT)
        self.assertIsNotNone(it["rsi14"])
        self.assertIn("mean_price_no_volume", it)
        self.assertEqual(m["reference_price"], ref)
        self.assertIn("above", m["nearest_levels"])
        self.assertIn("below", m["nearest_levels"])
        self.assertLess(m["nearest_levels"]["below"]["level"], ref)
        self.assertGreater(m["nearest_levels"]["above"]["level"], ref)

    def test_chain_trimmed_to_atm_window_with_oi_walls(self):
        m = C.market_context(daily=self.daily, intraday=self.intraday, chain=self.chain, now=self.now)
        ch = m["option_chain"]
        self.assertEqual(ch["atm"], 25000)
        self.assertEqual(ch["max_ce_oi_strike"], 25200)
        self.assertEqual(ch["max_pe_oi_strike"], 24800)
        self.assertEqual(ch["lot_size"], 65)
        strikes = [r["strike"] for r in ch["strikes_near_atm"]]
        self.assertEqual(strikes, list(range(24800, 25250, 50)))
        self.assertEqual(ch["strikes_near_atm"][0]["ce"]["ltp"], 100.0)
        self.assertTrue(m["session_clock"]["is_expiry_day"])
        self.assertEqual(m["session_clock"]["minutes_to_1515_squareoff"], 295)

    def test_stale_vix_dropped_and_partial_inputs_tolerated(self):
        from datetime import timedelta
        m = C.market_context(daily=self.daily, vix={"value": 13.0, "ts": self.now - timedelta(days=30)},
                             now=self.now)
        self.assertNotIn("india_vix", m)
        self.assertNotIn("intraday", m)
        self.assertIn("levels_from_prev_session", m)
        m2 = C.market_context(intraday=self.intraday, now=self.now)
        self.assertNotIn("daily", m2)
        self.assertNotIn("gap_pct", m2["intraday"])
        m3 = C.market_context(now=self.now)
        self.assertEqual(set(m3), {"symbol", "bar_minutes", "session_clock"})

    def test_snapshot_carries_market_and_prompt_allows_analysis(self):
        m = C.market_context(daily=self.daily, intraday=self.intraday, now=self.now)
        snap = C.build_snapshot(market=m, now=self.now)
        self.assertIs(snap["nifty_market"], m)
        body = json.dumps(snap, default=str)
        self.assertIn("levels_from_prev_session", body)
        self.assertIn("CE/PE", C.SYSTEM_PROMPT)
        self.assertIn("cannot place, exit, arm or toggle", C.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
