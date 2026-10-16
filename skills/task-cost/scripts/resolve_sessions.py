#!/usr/bin/env python3
"""Resolve one explicit/current Codex thread and known descendants, read-only."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys


def resolve(thread_id, home):
    notes = []
    sessions = []
    db = home / 'state_5.sqlite'
    if not db.exists():
        raise ValueError(f'Codex thread index unavailable: {db}; provide explicit rollout paths instead')
    connection = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'threads' not in tables:
            raise ValueError('Unsupported Codex thread index schema; provide explicit rollout paths')
        queue = [thread_id]
        seen = set()
        paths = set()
        if 'thread_spawn_edges' not in tables:
            notes.append('Subagent linkage unavailable; only the selected thread is included')
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            row = connection.execute('SELECT rollout_path FROM threads WHERE id = ?', (current,)).fetchone()
            if row is None:
                notes.append(f'Thread absent from index: {current}')
            elif row[0]:
                path = Path(row[0]).expanduser()
                if not path.is_absolute():
                    path = home / path
                path = path.resolve()
                if path.is_file() and str(path) not in paths:
                    paths.add(str(path))
                    sessions.append({'thread_id': current, 'path': str(path), 'is_root': current == thread_id})
                elif not path.is_file():
                    notes.append(f'Rollout unavailable for thread: {current}')
            else:
                notes.append(f'No rollout path for thread: {current}')
            if 'thread_spawn_edges' in tables:
                queue.extend(r[0] for r in connection.execute(
                    'SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id = ?', (current,)))
    finally:
        connection.close()
    notes.append('Includes only locally indexed spawn descendants; remote or unrecorded work may be missing')
    return {'thread_id': thread_id, 'sessions': sessions, 'coverage_notes': notes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thread', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', '~/.codex')).expanduser())
    args = parser.parse_args()
    if not args.thread:
        parser.error('No current thread ID exposed; supply --thread ID or explicit rollout paths to task_cost.py')
    try:
        result = resolve(args.thread, args.codex_home.expanduser())
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f'Cannot resolve session metadata: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result['sessions'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
