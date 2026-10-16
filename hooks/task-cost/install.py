#!/usr/bin/env python3
"""Install private USD task-cost hooks without changing Codex hook trust."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sys

from hook import private_write, load_rates

def owns_handler(handler, legacy):
    """Match only an exact direct/Python invocation of our installed old script."""
    if not isinstance(handler, dict) or handler.get('type') != 'command':
        return False
    try:
        argv = shlex.split(handler.get('command', ''))
    except (ValueError, TypeError):
        return False
    if not argv:
        return False
    def same_path(value):
        path = Path(value).expanduser()
        return path.is_absolute() and path.resolve() == legacy
    if len(argv) == 1:
        return same_path(argv[0])
    executable = Path(argv[0]).name
    if not (executable == 'python' or executable == 'python3' or executable.startswith('python3.')):
        return False
    index = 1
    while index < len(argv) and argv[index].startswith('-'):
        option = argv[index]
        if option in ('-W', '-X'):
            index += 2
        elif option in ('-u', '-B', '-I', '-s', '-S', '-E', '-O', '-OO', '-q', '-v') or option.startswith(('-W', '-X')):
            index += 1
        else:
            return False
    return index < len(argv) and same_path(argv[index]) and (index == len(argv) - 1 or (len(argv) == index + 3 and argv[index + 1] == '--rates'))


def validate_groups(groups, event):
    if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks'), list) for g in groups):
        raise ValueError(f'Existing {event} hook groups unsupported; left unchanged')


def install(home, repo, rates=None):
    home, repo = home.expanduser().resolve(), repo.expanduser().resolve()
    destination = home / 'hooks' / 'task-cost'
    script = destination / 'hook.py'
    card = Path(rates).expanduser() if rates else repo / 'skills' / 'task-cost' / 'references' / 'standard-usd-rates.json'
    if not card.is_absolute() or load_rates(card)['currency'] != 'USD':
        raise ValueError('An absolute USD rate card is required')
    sources = {destination / 'hook.py': repo / 'hooks' / 'task-cost' / 'hook.py',
               destination / 'scripts' / 'task_cost.py': repo / 'skills' / 'task-cost' / 'scripts' / 'task_cost.py',
               destination / 'scripts' / 'resolve_sessions.py': repo / 'skills' / 'task-cost' / 'scripts' / 'resolve_sessions.py',
               destination / 'references' / 'standard-usd-rates.json': repo / 'skills' / 'task-cost' / 'references' / 'standard-usd-rates.json'}
    contents = {target: source.read_text() for target, source in sources.items()}
    target = home / 'hooks.json'
    original = target.read_text() if target.exists() else None
    config = json.loads(original) if original is not None else {}
    if not isinstance(config, dict) or not isinstance(config.setdefault('hooks', {}), dict):
        raise ValueError('Unsupported existing hooks configuration; left unchanged')
    hooks = config['hooks']
    for event in ('PostToolUse', 'Stop'):
        validate_groups(hooks.setdefault(event, []), event)
    argv = [sys.executable, str(script)]
    if rates:
        argv.extend(['--rates', str(card)])
    handler = {'type': 'command', 'command': shlex.join(argv), 'timeout': 30,
               'statusMessage': 'Estimating task cost'}
    legacy = [(home / 'skills' / 'task-cost' / 'scripts' / name).resolve() for name in ('stop_hook.py', 'post_tool_use_hook.py')]
    changed = False
    for event in ('PostToolUse', 'Stop'):
        groups = []
        configured = False
        for group in hooks[event]:
            remaining = []
            for existing in group['hooks']:
                owns_current = owns_handler(existing, script)
                if owns_current and existing == handler and group.get('matcher', '') in ('', '*') and not configured:
                    configured = True
                    remaining.append(existing)
                elif owns_current or any(owns_handler(existing, path) for path in legacy):
                    changed = True
                else:
                    remaining.append(existing)
            if remaining or not group['hooks']:
                groups.append({**group, 'hooks': remaining})
        if not configured:
            groups.append({'hooks': [handler]})
            changed = True
        hooks[event] = groups
    # Finish validation and reading before any installation writes.
    for path, content in contents.items():
        if not path.exists() or path.read_text() != content:
            private_write(path, content)
    backup = None
    if changed:
        if original is not None:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = target.with_name('hooks.json.task-cost-backup-' + stamp)
            private_write(backup, original)
        private_write(target, json.dumps(config, indent=2) + '\n')
    return target, changed, backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or '~/.codex').expanduser())
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--rates', type=Path, help='Persist an absolute USD rate-card override')
    args = parser.parse_args(argv)
    try:
        target, changed, backup = install(args.codex_home, args.repo, args.rates)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f'Cannot install task-cost hooks: {exc}\n')
    print(f"{'Configured' if changed else 'Already configured'}: {target}")
    if backup:
        print(f'Backup: {backup}')
    print('Review and trust the PostToolUse and Stop entries through /hooks. No trust records were changed.')


if __name__ == '__main__':
    main()
