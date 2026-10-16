#!/usr/bin/env python3
"""Advisory PostToolUse hook: record an explicit turn's usage without model calls."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HELPERS = HERE / 'scripts' if (HERE / 'scripts').is_dir() else REPO / 'skills' / 'task-cost' / 'scripts'
sys.path.insert(0, str(HELPERS))

from resolve_sessions import resolve
from task_cost import build_report, load_rates, render_text, render_usd


def private_write(path, content):
    """Atomically replace a private file; never create world-readable reports."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.task-cost-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_session(path, expected):
    # Read only metadata; never use assistant/user text from the hook or rollout.
    with path.open() as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'session_meta':
                payload = event.get('payload')
                return isinstance(payload, dict) and payload.get('id') == expected
    return False


def _handle(event, home, rates_path):
    if not isinstance(event, dict) or event.get('hook_event_name') not in ('PostToolUse', 'Stop'):
        return {'systemMessage': 'unavailable'}
    identity = [event.get(key) for key in ('session_id', 'turn_id', 'transcript_path')]
    if not all(isinstance(value, str) and value.strip() for value in identity):
        return {'systemMessage': 'unavailable'}
    session_id, turn_id, transcript = identity
    notes = []
    report = None
    status = 'unavailable'
    try:
        path = Path(transcript).expanduser().resolve()
        if not path.is_file() or not verify_session(path, session_id):
            raise ValueError('Transcript identity could not be verified')
        paths = [path]
        try:
            linked = resolve(session_id, home)
            notes.extend(linked['coverage_notes'])
            for item in linked['sessions']:
                candidate = Path(item['path'])
                if not item['is_root'] and verify_session(candidate, item['thread_id']):
                    paths.append(candidate)
                elif not item['is_root']:
                    notes.append('A descendant transcript failed identity verification and was excluded.')
        except (ValueError, sqlite3.Error, OSError):
            notes.append('Local descendant index unavailable or unsupported; only the explicit transcript is included.')
        rates = load_rates(rates_path)
        if not rates or rates.get('currency') != 'USD':
            raise ValueError('USD rates required')
        report = build_report(paths, rates, turn=turn_id)
        status = 'recorded' if report['rows'] else 'unavailable'
        notes.append('Only proven descendants with matching turn_id/root_turn_id are attributed; other descendant work is excluded.')
        notes.append('Usage is provisional through the last recorded snapshot; usage snapshots may lag tool completion, and final tokens may be delayed. This is cumulative turn usage, not per-tool cost. Actual billed amount: unavailable.')
    except (ValueError, TypeError, KeyError, OSError):
        # Do not echo exception strings: they can contain untrusted transcript text.
        notes.append('Explicit transcript identity, usage schema, or packaged rates unavailable; no cost inferred.')
    document = {'schema_version': 1, 'session_id': session_id, 'turn_id': turn_id,
                'generated_at': datetime.now(timezone.utc).isoformat(), 'status': status,
                'coverage_notes': notes, 'report': report}
    key = hashlib.sha256((session_id + '\0' + turn_id).encode()).hexdigest()
    storage = home / 'task-cost'
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = storage / 'reports'
    directory.mkdir(exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    text = '# Task cost\n\n' + (render_text(report) if report else 'Usage unavailable; this does not establish zero cost.')
    text += '\n\n' + '\n'.join(notes) + '\n'
    private_write(directory / (key + '.json'), json.dumps(document, indent=2, allow_nan=False) + '\n')
    private_write(directory / (key + '.md'), text)
    # Advisory UI only: never pass tool/message contents or continuation output.
    return {'systemMessage': render_usd(report) if report else 'unavailable'}


def handle(event, home, rates_path):
    # Serialize each turn's calculation and both writes across concurrent tools.
    if not isinstance(event, dict) or event.get('hook_event_name') not in ('PostToolUse', 'Stop'):
        return _handle(event, home, rates_path)
    identity = [event.get(key) for key in ('session_id', 'turn_id', 'transcript_path')]
    if not all(isinstance(value, str) and value.strip() for value in identity):
        return _handle(event, home, rates_path)
    key = hashlib.sha256((identity[0] + '\0' + identity[1]).encode()).hexdigest()
    directory = home / 'task-cost' / 'locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / (key + '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _handle(event, home, rates_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rates', type=Path, help='Absolute USD rate-card override')
    args = parser.parse_args(argv)
    try:
        event = json.load(sys.stdin)
        home = Path(os.environ.get('CODEX_HOME') or '~/.codex').expanduser()
        override = args.rates or os.environ.get('TASK_COST_RATES')
        if override:
            rates = Path(override).expanduser()
            if not rates.is_absolute():
                raise ValueError('Absolute rate path required')
        else:
            local = HERE / 'references' / 'standard-usd-rates.json'
            rates = local if local.is_file() else REPO / 'skills' / 'task-cost' / 'references' / 'standard-usd-rates.json'
        result = handle(event, home, rates)
    except (ValueError, TypeError, OSError, UnicodeError):
        result = {'systemMessage': 'unavailable'}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
