#!/usr/bin/env python3
"""Legacy installer API; the command now delegates to repository USD hooks."""
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
    # The standalone skill no longer installs the obsolete credit-only hook.
    import subprocess
    parser = argparse.ArgumentParser(description='Install the repository USD hooks (legacy command).')
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or '~/.codex').expanduser())
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--rates', type=Path)
    args = parser.parse_args()
    installer = args.repo.expanduser().resolve() / 'hooks' / 'task-cost' / 'install.py'
    if not installer.is_file():
        parser.error('Use a checkout of elliotshohet/agents: python3 hooks/task-cost/install.py (or pass --repo /path/to/agents).')
    command = [sys.executable, str(installer), '--codex-home', str(args.codex_home)]
    if args.rates:
        command.extend(['--rates', str(args.rates)])
    return subprocess.call(command)


if __name__ == '__main__':
    raise SystemExit(main())
