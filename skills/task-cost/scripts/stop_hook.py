#!/usr/bin/env python3
"""Advisory Stop hook: record an explicit turn's usage without model calls."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from resolve_sessions import resolve
from task_cost import build_report, load_rates, render_text


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


def handle(event, home, rates_path):
    if not isinstance(event, dict) or event.get('hook_event_name') != 'Stop':
        return {'systemMessage': 'Task cost unavailable: expected a Stop hook event.'}
    identity = [event.get(key) for key in ('session_id', 'turn_id', 'transcript_path')]
    if not all(isinstance(value, str) and value.strip() for value in identity):
        return {'systemMessage': 'Task cost unavailable: Stop event lacks session_id, turn_id, or transcript_path; no session guessed.'}
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
        report = build_report(paths, load_rates(rates_path), turn=turn_id)
        status = 'recorded' if report['rows'] else 'unavailable'
        notes.append('Only proven descendants with matching turn_id/root_turn_id are attributed; other descendant work is excluded.')
        notes.append('Usage is provisional through the last recorded snapshot; final tokens may be delayed. Actual billed amount: unavailable.')
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
    if report and report['rows']:
        totals = report['totals']
        value = f"{totals['priced_subtotal']:.6f}" if totals['priced_events'] else 'unavailable'
        message = f"Task cost: provisional Standard credits subtotal {value}; {totals['unpriced_events']} unpriced snapshots"
        message += f"; recorded through {report['recorded_through'] or 'unknown'}."
        if not report['coverage_complete']:
            message += ' Usage coverage incomplete.'
        message += f" Standard-speed rates {report['rates']['verified_at'] or 'undated'}; actual billed amount unavailable. Indexed local scope only."
    else:
        message = 'Task cost unavailable for this turn; no cost inferred.'
    message += f' Reports: {directory / key}.json and .md'
    # systemMessage is UI-only. Never return block/reason/additionalContext.
    return {'systemMessage': message}


def main():
    try:
        event = json.load(sys.stdin)
        home = Path((os.environ.get('CODEX_HOME') or '~/.codex')).expanduser()
        result = handle(event, home, Path(__file__).resolve().parents[1] / 'references' / 'standard-credit-rates.json')
    except (ValueError, TypeError, OSError, UnicodeError):
        result = {'systemMessage': 'Task cost unavailable: invalid hook input or local report storage unavailable.'}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
