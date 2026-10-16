#!/usr/bin/env python3
"""Print current root session's recorded Codex account primary quota used%."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3

from resolve_sessions import resolve
from task_cost import timestamp

MAX_AGE_SECONDS = 15 * 60


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def usage_percent(path, thread_id, now=None):
    now = now or datetime.now(timezone.utc)
    identity = None
    latest_time = None
    latest = None
    invalid_timestamp = False
    with Path(path).open() as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                # A partial write cannot establish a current snapshot.
                return None
            if not isinstance(record, dict):
                continue
            payload = record.get('payload')
            if not isinstance(payload, dict):
                continue
            if record.get('type') == 'session_meta':
                candidate = payload.get('id')
                if identity is not None and candidate != identity:
                    return None
                identity = candidate
            if record.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                continue
            at = timestamp(record.get('timestamp'))
            if at is None:
                invalid_timestamp = True
                continue
            if latest_time is None or at >= latest_time:
                latest_time = at
                latest = payload.get('rate_limits', payload.get('rateLimits'))
    if not isinstance(identity, str) or not identity.strip() or (thread_id and identity != thread_id) or invalid_timestamp or latest_time is None:
        return None
    age = (now - latest_time).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS or not isinstance(latest, dict):
        return None
    if latest.get('limit_id', latest.get('limitId')) != 'codex':
        return None
    primary = latest.get('primary')
    if not isinstance(primary, dict):
        return None
    used = primary.get('used_percent', primary.get('usedPercent'))
    window = primary.get('window_minutes', primary.get('windowDurationMins'))
    reset = primary.get('resets_at', primary.get('resetsAt'))
    if not finite_number(used) or not 0 <= used <= 100:
        return None
    if not finite_number(window) or window <= 0 or not finite_number(reset):
        return None
    # Reset must be ahead of now and lie inside the snapshot's stated window.
    remaining = reset - now.timestamp()
    if remaining <= 0 or reset - latest_time.timestamp() > window * 60:
        return None
    return used


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thread', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or '~/.codex').expanduser())
    parser.add_argument('--session', type=Path, help='Explicit root rollout; session_meta establishes identity when --thread is not exposed')
    args = parser.parse_args(argv)
    try:
        thread_id = args.thread.strip() if isinstance(args.thread, str) else None
        path = args.session
        if path is None:
            if not thread_id:
                raise ValueError('No explicit current thread')
            selected = [item for item in resolve(thread_id, args.codex_home.expanduser())['sessions'] if item['is_root'] and item['thread_id'] == thread_id]
            if len(selected) != 1:
                raise ValueError('No root rollout')
            path = Path(selected[0]['path'])
        value = usage_percent(path.expanduser(), thread_id)
    except (OSError, ValueError, TypeError, OverflowError, sqlite3.Error):
        value = None
    print('unavailable' if value is None else f'{value:g}%')
    return 1 if value is None else 0


if __name__ == '__main__':
    raise SystemExit(main())
