import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import task_cost as cost


def event(kind, payload, at="2026-10-16T10:00:00Z"):
    return {"timestamp": at, "type": kind, "payload": payload}


def context(turn="t1", model="m1", at="2026-10-16T10:00:00Z", root="root"):
    return event("turn_context", {"turn_id": turn, "root_turn_id": root, "model": model}, at)


def usage(inp=100, cached=20, out=10, writes=0, reasoning=5, at="2026-10-16T10:00:01Z"):
    counters = {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
                "cache_write_input_tokens": writes, "reasoning_output_tokens": reasoning}
    counters = {k: v for k, v in counters.items() if v is not None}
    return event("event_msg", {"type": "token_count", "info": {"total_token_usage": counters, "last_token_usage": counters}}, at)


class CostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.rates = {"currency": "USD", "models": {"m1": {"input": 10, "cached_input": 1, "output": 20, "cache_write_input": 15}, "m2": {"input": 20, "cached_input": 2, "output": 40, "cache_write_input": 30}}}

    def report(self, entries, **kwargs):
        path = Path(self.temp.name) / "session.jsonl"
        path.write_text("\n".join(json.dumps(x) if not isinstance(x, str) else x for x in [event("session_meta", {"id": "s1", "timestamp": "2026-10-16T09:00:00Z"}), *entries]) + "\n")
        return cost.build_report([path], kwargs.pop("rates", self.rates), **kwargs)

    def test_cumulative_deduplicated_and_reasoning_subset(self):
        report = self.report([context(), usage(), usage(), usage(inp=150, cached=30, out=20, reasoning=8)])
        row = report["rows"][0]
        self.assertEqual(row["usage_events"], 2)
        self.assertEqual(row["usage"]["input_tokens"], 150)
        self.assertEqual(row["usage"]["output_tokens"], 20)
        self.assertAlmostEqual(row["estimate"], (120*10 + 30*1 + 20*20)/1e6)

    def test_cache_write_math(self):
        row = self.report([context(), usage(writes=10)])["rows"][0]
        self.assertAlmostEqual(row["estimate"], (70*10 + 20*1 + 10*15 + 10*20)/1e6)

    def test_models_and_turns_are_separate(self):
        report = self.report([context(), usage(), context("t2", "m2"), usage(inp=200, cached=40, out=20)])
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual([r["usage"]["input_tokens"] for r in report["rows"]], [100, 100])
        self.assertAlmostEqual(report["rows"][1]["estimate"], (80*20+20*2+10*40)/1e6)

    def test_since_preserves_baseline(self):
        report = self.report([context(), usage(), usage(inp=150, cached=30, out=20, at="2026-10-16T10:10:00Z")], since=cost.timestamp("2026-10-16T10:05:00Z"))
        self.assertEqual(report["rows"][0]["usage"]["input_tokens"], 50)

    def test_root_turn_filter(self):
        report = self.report([context(), usage(), context("t2", root="other"), usage(inp=200, cached=40, out=20)], turn="root")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(report["rows"][0]["root_turn_id"], "root")

    def test_unknown_and_missing_rate_are_not_zero(self):
        for rates in (None, {"currency": "USD", "models": {}}):
            report = self.report([context(), usage()], rates=rates)
            self.assertIsNone(report["totals"]["estimate"])
            self.assertEqual(report["totals"]["known_unpriced_tokens"], 110)

    def test_missing_cache_write_api_rate_unpriced(self):
        del self.rates["models"]["m1"]["cache_write_input"]
        self.assertIsNone(self.report([context(), usage(writes=10)])["totals"]["estimate"])
        self.assertIsNone(self.report([context(), usage(writes=None)])["totals"]["estimate"])

    def test_standard_credits_include_write_as_ordinary_input(self):
        self.rates.update(currency="credits", billing_mode="codex_credits")
        del self.rates["models"]["m1"]["cache_write_input"]
        for writes in (10, None):
            report = self.report([context(), usage(writes=writes)])
            self.assertAlmostEqual(report["totals"]["estimate"], (80*10 + 20 + 10*20)/1e6)
            self.assertIn("Standard credits", report["label"])

    def test_malformed_and_unsupported_usage_warn(self):
        report = self.report(["{truncated", context(), usage(), event("event_msg", {"type": "token_count", "info": {"other": {}}})])
        self.assertEqual(len(report["warnings"]), 2)
        self.assertIsNone(report["totals"]["estimate"])
        self.assertEqual(report["totals"]["unreadable_usage_events"], 1)

    def test_missing_counter_unpriced(self):
        self.assertIsNone(self.report([context(), usage(cached=None)])["totals"]["estimate"])

    def test_invalid_subset_unpriced(self):
        for event_usage in (usage(reasoning=11), usage(cached=101), usage(cached=90, writes=11)):
            report = self.report([context(), event_usage])
            self.assertIsNone(report["totals"]["estimate"])
            self.assertFalse(report["coverage_complete"])

    def test_recorded_through_and_malformed_coverage(self):
        report = self.report([context(), usage()])
        self.assertEqual(report["recorded_through"], "2026-10-16T10:00:01+00:00")
        self.assertTrue(report["coverage_complete"])
        malformed = self.report([context(), usage(), "{truncated"])
        self.assertFalse(malformed["coverage_complete"])
        self.assertIsNone(malformed["totals"]["estimate"])
        self.assertGreater(malformed["totals"]["priced_subtotal"], 0)

    def test_inherited_prefix_excluded_but_baseline_preserved(self):
        report = self.report([context(at="2026-10-16T08:00:00Z"), usage(), context(), usage(inp=150, cached=30, out=20)])
        self.assertEqual(report["rows"][0]["usage"]["input_tokens"], 50)
        self.assertTrue(report["warnings"])

    def test_usd_only_direct_and_explicit_credit_conversion(self):
        report = self.report([context(), usage(inp=40000, cached=0, out=1000, reasoning=0)])
        self.assertEqual(cost.render_usd(report), '$0.42')
        self.rates.update(currency='credits', billing_mode='codex_credits')
        credits = self.report([context(), usage(inp=40000, cached=0, out=1000, reasoning=0)])
        self.assertEqual(cost.render_usd(credits), 'unavailable')
        self.assertEqual(cost.render_usd(credits, 2), '$0.84')

    def test_usd_only_never_formats_partial_or_unknown_as_total(self):
        for entries, kwargs in [([context(), usage(), '{bad'], {}),
                                ([context(), usage()], {'rates': None}),
                                ([context(), usage()], {'turn': 'missing'}),
                                ([context(), usage(), context('t2', 'unknown'), usage(inp=200, out=20)], {})]:
            self.assertEqual(cost.render_usd(self.report(entries, **kwargs)), 'unavailable')

    def test_invalid_usd_conversion_rejected(self):
        for value in ('0', '-1', 'nan', 'inf', 'not-a-rate'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                cost.main(['--session', '/unused', '--usd-only', '--usd-per-credit', value])
            self.assertEqual(raised.exception.code, 2)

    def test_usd_cli_exclusive_and_unavailable_exit(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cost.main(['--session', '/unused', '--usd-only', '--json'])
        self.assertEqual(raised.exception.code, 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cost.main(['--session', str(Path(self.temp.name) / 'missing'), '--usd-only'])
        self.assertNotEqual(code, 0)
        self.assertEqual(output.getvalue(), 'unavailable\n')

    def test_usd_cli_formats_complete_report_only(self):
        self.report([context(), usage(inp=40000, cached=0, out=1000, reasoning=0)])
        rates = Path(self.temp.name) / 'rates.json'
        rates.write_text(json.dumps(self.rates))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cost.main(['--session', str(Path(self.temp.name) / 'session.jsonl'), '--rates', str(rates), '--usd-only'])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), '$0.42\n')

    def test_credit_cli_requires_explicit_conversion(self):
        self.rates.update(currency='credits', billing_mode='codex_credits')
        self.report([context(), usage(inp=40000, cached=0, out=1000, reasoning=0)])
        rates = Path(self.temp.name) / 'rates.json'
        rates.write_text(json.dumps(self.rates))
        args = ['--session', str(Path(self.temp.name) / 'session.jsonl'), '--rates', str(rates), '--usd-only']
        for extra, expected, status in [([], 'unavailable\n', 1), (['--usd-per-credit', '2'], '$0.84\n', 0)]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cost.main(args + extra)
            self.assertEqual(code, status)
            self.assertEqual(output.getvalue(), expected)

    def test_bad_rate_rejected(self):
        path = Path(self.temp.name) / "rates.json"
        for value in (-1, float("nan"), True, "10"):
            path.write_text(json.dumps({"currency": "USD", "models": {"m1": {"input": value}}}))
            with self.assertRaises(ValueError):
                cost.load_rates(path)

    def context_rates(self):
        card = self.rates["models"]["m1"]
        card["long_context_threshold"] = 272000
        card["long_context"] = {"input": 20, "cached_input": 2,
                                "cache_write_input": 30, "output": 30}
        return self.rates

    def test_context_threshold_boundary_prices_whole_request(self):
        rates = self.context_rates()
        for inp, expected in [(272000, (271970*10 + 20 + 150 + 200)/1e6),
                              (272001, (271971*20 + 40 + 300 + 300)/1e6)]:
            report = self.report([context(), usage(inp=inp, writes=10)], rates=rates)
            self.assertAlmostEqual(report["totals"]["estimate"], expected)

    def test_mixed_short_and_long_requests_in_same_row(self):
        rates = self.context_rates()
        second = usage(inp=272101, cached=40, writes=20, out=20, reasoning=10)
        second["payload"]["info"]["last_token_usage"] = dict(second["payload"]["info"]["last_token_usage"])
        second["payload"]["info"]["last_token_usage"]["input_tokens"] = 272001
        report = self.report([context(), usage(writes=10), second], rates=rates)
        self.assertEqual(report["totals"]["priced_events"], 2)
        self.assertAlmostEqual(report["totals"]["estimate"],
                               (70*10 + 20 + 150 + 200 + 271971*20 + 40 + 300 + 300)/1e6)

    def test_cumulative_total_crossing_threshold_keeps_small_delta_short(self):
        rates = self.context_rates()
        # Even missing last-request data is sufficient when each delta is small.
        second = usage(inp=272100, cached=40, out=20, reasoning=10)
        second["payload"]["info"].pop("last_token_usage")
        report = self.report([context(), usage(inp=272000), second], rates=rates)
        self.assertAlmostEqual(report["totals"]["estimate"],
                               ((272100-40)*10 + 40 + 20*20)/1e6)

    def test_large_aggregated_snapshot_context_band_is_unpriced(self):
        rates = self.context_rates()
        for last in ({"input_tokens": 100}, {}, None, {"input_tokens": True}):
            snapshot = usage(inp=300000)
            snapshot["payload"]["info"]["last_token_usage"] = last
            report = self.report([context(), snapshot], rates=rates)
            self.assertIsNone(report["totals"]["estimate"])
            self.assertIn("context band ambiguous", report["rows"][0]["unpriced_reasons"][0])

    def test_invalid_context_cards_rejected(self):
        path = Path(self.temp.name) / "rates.json"
        for threshold in (None, 0, -1, True, 272000.0, "272000"):
            rates = self.context_rates()
            rates["models"]["m1"]["long_context_threshold"] = threshold
            path.write_text(json.dumps(rates))
            with self.assertRaises(ValueError):
                cost.load_rates(path)
        for nested in (None, [], 10, {"input": -1}, {"output": float("inf")},
                       {"cached_input": True}, {"cache_write_input": "30"},
                       {"input": 10**1000}):
            rates = self.context_rates()
            rates["models"]["m1"]["long_context"] = nested
            path.write_text(json.dumps(rates))
            with self.assertRaises(ValueError):
                cost.load_rates(path)
        rates = self.context_rates()
        del rates["models"]["m1"]["long_context"]
        path.write_text(json.dumps(rates))
        with self.assertRaises(ValueError):
            cost.load_rates(path)

    def test_context_card_roundtrip_and_missing_nested_rate_not_base_fallback(self):
        rates = self.context_rates()
        path = Path(self.temp.name) / "rates.json"
        path.write_text(json.dumps(rates))
        self.assertEqual(cost.load_rates(path), rates)
        del rates["models"]["m1"]["long_context"]["output"]
        report = self.report([context(), usage(inp=272001)], rates=rates)
        self.assertIsNone(report["totals"]["estimate"])
        self.assertEqual(report["rows"][0]["unpriced_reasons"], ["missing rates: output"])


if __name__ == "__main__":
    unittest.main()
