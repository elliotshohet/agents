import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import install_hook
import stop_hook
from test_task_cost import context, event, usage

RATES = Path(__file__).resolve().parents[1] / 'references' / 'standard-credit-rates.json'


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.rollout('root', 't1')
        self.input = {'hook_event_name': 'Stop', 'session_id': 'root', 'turn_id': 't1',
                      'transcript_path': str(self.root), 'last_assistant_message': 'PRIVATE_MESSAGE'}

    def rollout(self, name, turn, root_turn=None):
        path = self.home / (name + '.jsonl')
        events = [event('session_meta', {'id': name, 'timestamp': '2026-10-16T09:00:00Z'}),
                  context(turn, 'gpt-6.1-sol', root=root_turn), usage()]
        path.write_text('\n'.join(map(json.dumps, events)) + '\n')
        return path

    def documents(self):
        return [json.loads(p.read_text()) for p in (self.home / 'task-cost' / 'reports').glob('*.json')]

    def test_explicit_turn_private_idempotent_reports_and_no_continuation(self):
        output = stop_hook.handle(self.input, self.home, RATES)
        self.assertEqual(set(output), {'systemMessage'})
        self.assertIn('provisional', output['systemMessage'])
        stop_hook.handle(self.input, self.home, RATES)
        documents = self.documents()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]['report']['totals']['usage_events'], 1)
        self.assertIn('Actual billed amount', ' '.join(documents[0]['coverage_notes']))
        for path in (self.home / 'task-cost' / 'reports').iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn('PRIVATE_MESSAGE', path.read_text())

    def test_only_proven_descendants_with_matching_root_turn(self):
        child = self.rollout('child', 'childturn', 't1')
        other = self.rollout('unrelated', 't1')
        db = sqlite3.connect(self.home / 'state_5.sqlite')
        db.executescript('CREATE TABLE threads(id TEXT, rollout_path TEXT); CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT);')
        db.executemany('INSERT INTO threads VALUES (?, ?)', [('root', str(self.root)), ('child', str(child)), ('unrelated', str(other))])
        db.execute('INSERT INTO thread_spawn_edges VALUES (?, ?)', ('root', 'child'))
        db.commit()
        db.close()
        stop_hook.handle(self.input, self.home, RATES)
        rows = self.documents()[0]['report']['rows']
        self.assertEqual({row['session_id'] for row in rows}, {'root', 'child'})
        self.assertEqual(sum(row['usage']['input_tokens'] for row in rows), 200)

    def test_missing_identity_never_guesses(self):
        for key in ('session_id', 'turn_id', 'transcript_path'):
            payload = dict(self.input)
            payload.pop(key)
            self.assertIn('no session guessed', stop_hook.handle(payload, self.home, RATES)['systemMessage'])
        self.assertFalse((self.home / 'task-cost').exists())

    def test_wrong_identity_unavailable(self):
        self.input['session_id'] = 'wrong'
        self.assertIn('unavailable', stop_hook.handle(self.input, self.home, RATES)['systemMessage'])
        self.assertIsNone(self.documents()[0]['report'])

    def test_other_turn_not_counted_as_zero_cost(self):
        self.input['turn_id'] = 't2'
        self.assertIn('unavailable', stop_hook.handle(self.input, self.home, RATES)['systemMessage'])
        self.assertIsNone(self.documents()[0]['report']['totals']['estimate'])

    def test_malformed_usage_disclosed(self):
        with self.root.open('a') as stream:
            stream.write('{broken\n')
        output = stop_hook.handle(self.input, self.home, RATES)
        self.assertIn('incomplete', output['systemMessage'])
        self.assertIsNone(self.documents()[0]['report']['totals']['estimate'])

    def test_bad_hook_json_returns_nonblocking_json(self):
        result = subprocess.run([sys.executable, str(Path(stop_hook.__file__))], input='{bad', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(set(json.loads(result.stdout)), {'systemMessage'})
        self.assertFalse(result.stderr)

    def test_installer_merges_backs_up_and_is_idempotent(self):
        skill = self.home / 'installed skill'
        (skill / 'scripts').mkdir(parents=True)
        (skill / 'scripts' / 'stop_hook.py').write_text('# installed')
        old = {'description': 'Keep me', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing notify'}]}], 'SessionStart': [{'hooks': []}]}, 'custom': True}
        target = self.home / 'hooks.json'
        original = json.dumps(old)
        target.write_text(original)
        os.chmod(self.home, 0o755)
        path, changed, backup = install_hook.install(self.home, skill)
        self.assertTrue(changed)
        self.assertEqual(stat.S_IMODE(self.home.stat().st_mode), 0o755)
        self.assertEqual(backup.read_text(), original)
        result = json.loads(path.read_text())
        self.assertEqual(result['hooks']['Stop'][0], old['hooks']['Stop'][0])
        self.assertEqual(result['hooks']['SessionStart'], old['hooks']['SessionStart'])
        self.assertTrue(result['custom'])
        self.assertEqual(install_hook.install(self.home, skill)[1:], (False, None))
        self.assertEqual(len(list(self.home.glob('hooks.json.task-cost-backup-*'))), 1)
        self.assertFalse(any('trust' in p.name for p in self.home.iterdir()))

    def test_empty_codex_home_uses_default_in_both_entrypoints(self):
        with patch.dict(os.environ, {'CODEX_HOME': ''}), patch.object(sys, 'stdin', io.StringIO(json.dumps(self.input))), patch.object(stop_hook, 'handle', return_value={}) as handler, contextlib.redirect_stdout(io.StringIO()):
            stop_hook.main()
            self.assertEqual(handler.call_args.args[1], Path('~/.codex').expanduser())
        with patch.dict(os.environ, {'CODEX_HOME': '', 'HOME': str(self.home)}), patch.object(sys, 'argv', ['install_hook.py']), patch('subprocess.call', return_value=0) as installer:
            self.assertEqual(install_hook.main(), 0)
            command = installer.call_args.args[0]
            self.assertEqual(command[command.index('--codex-home') + 1], str(self.home / '.codex'))
            self.assertFalse((self.home / '.codex' / 'hooks.json').exists())

    def test_unsupported_usage_unavailable(self):
        self.root.write_text(json.dumps(event('session_meta', {'id': 'root'})) + '\n' + json.dumps(event('event_msg', {'type': 'token_count', 'info': {'other': {}}})) + '\n')
        self.assertIn('unavailable', stop_hook.handle(self.input, self.home, RATES)['systemMessage'])
        self.assertIsNone(self.documents()[0]['report']['totals']['estimate'])
        self.assertEqual(self.documents()[0]['report']['totals']['unreadable_usage_events'], 1)

    def test_bad_config_left_unchanged(self):
        target = self.home / 'hooks.json'
        target.write_text('{bad')
        with self.assertRaises(ValueError):
            install_hook.install(self.home, Path(stop_hook.__file__).parents[1])
        self.assertEqual(target.read_text(), '{bad')


if __name__ == '__main__':
    unittest.main()
