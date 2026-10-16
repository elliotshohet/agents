import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import usage_percent as percent


class UsagePercentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'root.jsonl'
        self.now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    def snapshot(self, used=33, age=0, **changes):
        limits = {'limit_id': 'codex', 'primary': {'used_percent': used, 'window_minutes': 300, 'resets_at': self.now.timestamp() + 3600}, 'credits': {'balance': 'PRIVATE_BALANCE'}}
        limits.update(changes)
        return {'timestamp': (self.now - timedelta(seconds=age)).isoformat(), 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': limits}}

    def write(self, *records, identity='root'):
        meta = {'type': 'session_meta', 'payload': {'id': identity}}
        self.path.write_text('\n'.join(json.dumps(r) for r in (meta, *records)) + '\n')
        return percent.usage_percent(self.path, 'root', self.now)

    def test_valid_zero_and_fraction(self):
        for used in (0, 33, 33.5, 100):
            self.assertEqual(self.write(self.snapshot(used)), used)

    def test_newest_timestamp_wins_over_file_order(self):
        self.assertEqual(self.write(self.snapshot(33.5), self.snapshot(10, age=60)), 33.5)

    def test_latest_missing_null_or_unknown_never_falls_back(self):
        for latest in (None, {}, {'limit_id': 'other', 'primary': {'used_percent': 80}}):
            current = self.snapshot()
            current['payload']['rate_limits'] = latest
            self.assertIsNone(self.write(self.snapshot(20, age=60), current))
        current['payload'].pop('rate_limits')
        self.assertIsNone(self.write(self.snapshot(20, age=60), current))

    def test_invalid_percentage_and_window(self):
        for used in (None, True, -1, 101, '33', float('inf'), float('nan')):
            self.assertIsNone(self.write(self.snapshot(used)))
        for field, value in [('window_minutes', 0), ('window_minutes', True), ('resets_at', None), ('resets_at', float('nan'))]:
            current = self.snapshot()
            current['payload']['rate_limits']['primary'][field] = value
            self.assertIsNone(self.write(current))

    def test_expired_stale_future_and_invalid_timestamp(self):
        current = self.snapshot()
        current['payload']['rate_limits']['primary']['resets_at'] = self.now.timestamp()
        self.assertIsNone(self.write(current))
        self.assertIsNone(self.write(self.snapshot(age=901)))
        self.assertIsNone(self.write(self.snapshot(age=-1)))
        current['timestamp'] = 'unknown'
        self.assertIsNone(self.write(self.snapshot(), current))

    def test_wrong_identity_and_missing_snapshot(self):
        self.assertIsNone(self.write(self.snapshot(), identity='other'))
        self.assertIsNone(self.write())

    def test_camel_case_schema(self):
        current = self.snapshot()
        current['payload']['rate_limits'] = {'limitId': 'codex', 'primary': {'usedPercent': 33.5, 'windowDurationMins': 300, 'resetsAt': self.now.timestamp() + 3600}}
        self.assertEqual(self.write(current), 33.5)

    def test_cli_raw_output_and_no_sensitive_metadata(self):
        self.write(self.snapshot())
        for value, expected, code in [(0, '0%\n', 0), (33.5, '33.5%\n', 0), (None, 'unavailable\n', 1)]:
            output = io.StringIO()
            with patch.object(percent, 'usage_percent', return_value=value), contextlib.redirect_stdout(output):
                status = percent.main(['--thread', 'root', '--session', str(self.path)])
            self.assertEqual(output.getvalue(), expected)
            self.assertEqual(status, code)

    def test_explicit_path_can_supply_identity_without_thread_environment(self):
        self.write(self.snapshot())
        self.assertEqual(percent.usage_percent(self.path, None, self.now), 33)
        with patch.dict(os.environ, {'CODEX_THREAD_ID': ''}), patch.object(percent, 'usage_percent', return_value=33) as usage, patch.object(percent, 'resolve') as resolver, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(percent.main(['--session', str(self.path)]), 0)
            usage.assert_called_once_with(self.path, '')
            resolver.assert_not_called()

    def test_no_latest_unrelated_session_guess_and_only_root_selected(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'CODEX_THREAD_ID': ''}), patch.object(percent, 'resolve') as resolver, contextlib.redirect_stdout(output):
            self.assertEqual(percent.main(['--codex-home', self.temp.name]), 1)
            resolver.assert_not_called()
        self.assertEqual(output.getvalue(), 'unavailable\n')
        metadata = {'sessions': [{'is_root': False, 'thread_id': 'child', 'path': '/never-read-child'}, {'is_root': True, 'thread_id': 'root', 'path': str(self.path)}]}
        with patch.object(percent, 'resolve', return_value=metadata), patch.object(percent, 'usage_percent', return_value=33) as usage, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(percent.main(['--thread', 'root']), 0)
            usage.assert_called_once_with(self.path, 'root')


if __name__ == '__main__':
    unittest.main()
