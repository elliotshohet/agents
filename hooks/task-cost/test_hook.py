import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shlex
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hook
import install

REPO = Path(__file__).resolve().parents[2]


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.rates = self.home / 'rates.json'
        self.card = {'currency': 'USD', 'models': {'model': {'input': 10, 'cached_input': 1, 'output': 20, 'cache_write_input': 10}}}
        self.rates.write_text(json.dumps(self.card))
        self.root = self.rollout('root', 'turn')
        self.event = {'hook_event_name': 'PostToolUse', 'session_id': 'root', 'turn_id': 'turn', 'transcript_path': str(self.root), 'tool_input': 'PRIVATE_INPUT', 'tool_response': 'PRIVATE_RESULT', 'last_assistant_message': 'PRIVATE_MESSAGE'}

    def usage(self, inp=40000, out=1000):
        return {'timestamp': '2026-10-16T12:00:01Z', 'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': inp, 'cached_input_tokens': 0, 'cache_write_input_tokens': 0, 'output_tokens': out, 'reasoning_output_tokens': 0}}}}

    def rollout(self, name, turn, root=None):
        path = self.home / (name + '.jsonl')
        records = [{'timestamp': '2026-10-16T10:00:00Z', 'type': 'session_meta', 'payload': {'id': name}}, {'timestamp': '2026-10-16T12:00:00Z', 'type': 'turn_context', 'payload': {'turn_id': turn, 'root_turn_id': root, 'model': 'model'}}, self.usage()]
        path.write_text('\n'.join(map(json.dumps, records)) + '\n')
        return path

    def report(self):
        paths = list((self.home / 'task-cost' / 'reports').glob('*.json'))
        self.assertEqual(len(paths), 1)
        return json.loads(paths[0].read_text())

    def test_both_events_refresh_same_turn_without_double_counting(self):
        self.assertEqual(hook.handle(self.event, self.home, self.rates), {'systemMessage': '$0.42'})
        self.event['hook_event_name'] = 'Stop'
        with self.root.open('a') as stream:
            stream.write(json.dumps(self.usage(50000, 2000)) + '\n')
        self.assertEqual(hook.handle(self.event, self.home, self.rates), {'systemMessage': '$0.54'})
        self.assertEqual(self.report()['report']['rows'][0]['usage']['input_tokens'], 50000)

    def test_private_reports_never_include_tool_or_message_bodies(self):
        hook.handle(self.event, self.home, self.rates)
        for path in (self.home / 'task-cost' / 'reports').iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn('PRIVATE_', path.read_text())

    def test_missing_identity_invalid_event_partial_and_credit_rates_unavailable(self):
        for key in ('session_id', 'turn_id', 'transcript_path'):
            event = dict(self.event)
            event.pop(key)
            self.assertEqual(hook.handle(event, self.home, self.rates), {'systemMessage': 'unavailable'})
        self.assertEqual(hook.handle({}, self.home, self.rates), {'systemMessage': 'unavailable'})
        with self.root.open('a') as stream:
            stream.write('{truncated\n')
        self.assertEqual(hook.handle(self.event, self.home, self.rates), {'systemMessage': 'unavailable'})
        self.assertGreater(self.report()['report']['totals']['priced_subtotal'], 0)
        self.card.update(currency='credits', billing_mode='codex_credits')
        self.rates.write_text(json.dumps(self.card))
        self.assertEqual(hook.handle(self.event, self.home, self.rates), {'systemMessage': 'unavailable'})

    def test_only_proven_descendants_are_included(self):
        child = self.rollout('child', 'childturn', 'turn')
        self.rollout('unrelated', 'turn')
        db = sqlite3.connect(self.home / 'state_5.sqlite')
        db.executescript('CREATE TABLE threads(id TEXT, rollout_path TEXT); CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT);')
        db.executemany('INSERT INTO threads VALUES (?, ?)', [('root', str(self.root)), ('child', str(child))])
        db.execute('INSERT INTO thread_spawn_edges VALUES (?, ?)', ('root', 'child'))
        db.commit()
        db.close()
        self.assertEqual(hook.handle(self.event, self.home, self.rates), {'systemMessage': '$0.84'})
        self.assertEqual({r['session_id'] for r in self.report()['report']['rows']}, {'root', 'child'})

    def test_parallel_refreshes_are_serialized(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: hook.handle(self.event, self.home, self.rates), range(8)))
        self.assertEqual(results, [{'systemMessage': '$0.42'}] * 8)
        self.assertEqual(self.report()['report']['totals']['usage_events'], 1)
        self.assertEqual(len(list((self.home / 'task-cost' / 'reports').glob('*.md'))), 1)

    def fixture_repo(self):
        repo = self.home / 'repo'
        sources = ['hooks/task-cost/hook.py', 'skills/task-cost/scripts/task_cost.py', 'skills/task-cost/scripts/resolve_sessions.py']
        for name in sources:
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((REPO / name).read_text())
        path = repo / 'skills/task-cost/references/standard-usd-rates.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.card))
        return repo

    def test_install_migration_preserves_mixed_groups_and_is_idempotent(self):
        repo = self.fixture_repo()
        legacy = self.home / 'skills/task-cost/scripts/stop_hook.py'
        old = {'type': 'command', 'command': shlex.join([sys.executable, '-u', str(legacy)])}
        notify = {'type': 'command', 'command': 'keep notify'}
        config = {'description': 'keep', 'hooks': {'Stop': [{'matcher': 'keep', 'other': True, 'hooks': [old, notify]}, {'hooks': []}], 'PostToolUse': [{'hooks': [{'type': 'command', 'command': 'echo ' + shlex.quote(str(legacy))}]}]}}
        original = json.dumps(config)
        (self.home / 'hooks.json').write_text(original)
        target, changed, backup = install.install(self.home, repo)
        self.assertTrue(changed)
        self.assertEqual(backup.read_text(), original)
        result = json.loads(target.read_text())
        self.assertEqual(result['hooks']['Stop'][0], {'matcher': 'keep', 'other': True, 'hooks': [notify]})
        self.assertEqual(result['hooks']['Stop'][1], {'hooks': []})
        self.assertEqual(result['hooks']['PostToolUse'][0], config['hooks']['PostToolUse'][0])
        self.assertEqual(install.install(self.home, repo)[1:], (False, None))
        self.assertFalse(any('trust' in p.name for p in self.home.iterdir()))
        runtime = self.home / 'hooks/task-cost/hook.py'
        process = subprocess.run([sys.executable, str(runtime)], input=json.dumps(self.event), text=True, capture_output=True, env={**os.environ, 'CODEX_HOME': str(self.home), 'TASK_COST_RATES': ''})
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout), {'systemMessage': '$0.42'})
        self.assertFalse(process.stderr)

    def test_rate_override_persists_and_relative_or_credit_rejected(self):
        repo = self.fixture_repo()
        target, _, _ = install.install(self.home, repo, self.rates)
        command = json.loads(target.read_text())['hooks']['Stop'][0]['hooks'][0]['command']
        self.assertEqual(shlex.split(command)[-2:], ['--rates', str(self.rates)])
        with self.assertRaises(ValueError):
            install.install(self.home, repo, Path('relative.json'))
        self.card.update(currency='credits', billing_mode='codex_credits')
        self.rates.write_text(json.dumps(self.card))
        with self.assertRaises(ValueError):
            install.install(self.home, repo, self.rates)

    def test_malformed_stdin_is_nonblocking_raw_unavailable(self):
        process = subprocess.run([sys.executable, str(REPO / 'hooks/task-cost/hook.py')], input='{bad', text=True, capture_output=True)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout), {'systemMessage': 'unavailable'})
        self.assertFalse(process.stderr)


if __name__ == '__main__':
    unittest.main()
