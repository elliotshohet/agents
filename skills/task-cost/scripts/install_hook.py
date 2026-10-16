#!/usr/bin/env python3
"""Merge the task-cost Stop hook into Codex hooks.json; never modify hook trust."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sys

from stop_hook import private_write


def install(home, skill_dir):
    script = (skill_dir / 'scripts' / 'stop_hook.py').resolve()
    if not script.is_file():
        raise ValueError('Install the task-cost skill before configuring its hook')
    target = home / 'hooks.json'
    original = target.read_text() if target.exists() else None
    config = json.loads(original) if original is not None else {}
    if not isinstance(config, dict):
        raise ValueError('Existing hooks.json must be an object; left unchanged')
    hooks = config.setdefault('hooks', {})
    if not isinstance(hooks, dict):
        raise ValueError('Existing hooks field must be an object; left unchanged')
    groups = hooks.setdefault('Stop', [])
    if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks'), list) for g in groups):
        raise ValueError('Existing Stop hook groups unsupported; left unchanged')
    command = shlex.join([sys.executable, str(script)])
    handler = {'type': 'command', 'command': command, 'timeout': 30,
               'statusMessage': 'Recording task cost'}
    if any(handler == existing for group in groups for existing in group['hooks']):
        return target, False, None
    groups.append({'hooks': [handler]})
    backup = None
    if original is not None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = target.with_name('hooks.json.task-cost-backup-' + stamp)
        private_write(backup, original)
    private_write(target, json.dumps(config, indent=2) + '\n')
    return target, True, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path((os.environ.get('CODEX_HOME') or '~/.codex')).expanduser())
    parser.add_argument('--skill-dir', type=Path, help='Stable installed skill directory (default: CODEX_HOME/skills/task-cost)')
    args = parser.parse_args()
    home = args.codex_home.expanduser().resolve()
    try:
        target, changed, backup = install(home, (args.skill_dir or home / 'skills' / 'task-cost').expanduser())
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'Cannot install task-cost hook: {exc}\n')
    print(f"{'Configured' if changed else 'Already configured'}: {target}")
    if backup:
        print(f'Backup: {backup}')
    print('Open /hooks in Codex to review and trust this hook. No trust records were changed. Reload/start a session if needed.')


if __name__ == '__main__':
    main()
