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
        self.assertEqual(kw["output_config"], {"effort": "low"})
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(kw["extra_body"], {"fallbacks": "default"})
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertNotIn("thinking", kw)            # Opus 5.5: thinking is always on; effort steers it
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


if __name__ == "__main__":
    unittest.main()
