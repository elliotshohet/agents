#!/usr/bin/env python3
"""Estimate scoped Codex usage from explicit rollout JSONL files, without content."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

COUNTERS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens")


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def counter(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def load_rates(path):
    if path is None:
        return None
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        raise ValueError("rates must contain a models object")
    currency = data.get("currency")
    mode = data.get("billing_mode", "api_equivalent")
    if mode not in ("api_equivalent", "codex_credits"):
        raise ValueError("billing_mode must be api_equivalent or codex_credits")
    if currency not in ("USD", "credits") or (mode == "codex_credits" and currency != "credits") or (mode == "api_equivalent" and currency != "USD"):
        raise ValueError("codex_credits requires credits; api_equivalent requires USD")
    for model, rates in data["models"].items():
        if not isinstance(model, str) or not isinstance(rates, dict):
            raise ValueError("each exact model ID must map to a rate object")
        for name, value in rates.items():
            if name in ("input", "cached_input", "output", "cache_write_input"):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid nonnegative finite rate: {model}.{name}")
    return data


def price(usage, model, rates):
    if model == "unknown":
        return None, "model unavailable"
    if not rates:
        return None, "no rate card supplied"
    card = rates["models"].get(model)
    if card is None:
        return None, "exact model has no rate"
    inp, cached, out = (usage.get(k) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
    if inp is None or cached is None or out is None:
        return None, "missing input, cache, or output counter"
    writes = usage.get("cache_write_input_tokens")
    reasoning = usage.get("reasoning_output_tokens")
    if reasoning is not None and reasoning > out:
        return None, "reasoning counter exceeds output (reasoning is a subset)"
    if cached + (writes or 0) > inp:
        return None, "cache categories exceed input"
    if rates.get("billing_mode") == "codex_credits":
        writes = 0  # Codex Standard input rate includes writes.
    elif writes is None:
        return None, "cache-write counter unavailable for API estimate"
    if cached + writes > inp:
        return None, "cache categories exceed input"
    amounts = {"input": inp - cached - writes, "cached_input": cached, "output": out, "cache_write_input": writes}
    missing = [key for key, amount in amounts.items() if amount and key not in card]
    if missing:
        return None, "missing rates: " + ", ".join(missing)
    return sum(amount * card.get(key, 0) / 1_000_000 for key, amount in amounts.items()), None


def build_report(paths, rates=None, turn=None, since=None, until=None):
    rows = {}
    warnings = set()
    session_count = 0
    unreadable_usage_events = 0
    coverage_complete = True
    recorded_through = None
    seen_paths = set()
    for filename in paths:
        path = Path(filename).expanduser().resolve()
        if path in seen_paths:
            warnings.add("Repeated session path ignored.")
            continue
        seen_paths.add(path)
        session_count += 1
        session_id = "unknown:" + path.name
        own_start = None
        context = {}
        context_time = None
        previous = {}
        seen_snapshots = set()
        found_tokens = False
        with path.open() as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    coverage_complete = False
                    warnings.add(f"{path.name}:{line_number}: malformed/truncated line skipped.")
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    if event.get("type") in ("session_meta", "turn_context", "event_msg"):
                        coverage_complete = False
                        warnings.add(f"{path.name}: unsupported metadata/event payload schema.")
                    continue
                kind = event.get("type")
                if kind == "session_meta":
                    session_id = payload.get("id") or session_id
                    own_start = timestamp(payload.get("timestamp")) or timestamp(event.get("timestamp"))
                    continue
                if kind == "turn_context":
                    context = payload
                    context_time = timestamp(event.get("timestamp"))
                    continue
                if kind != "event_msg" or payload.get("type") != "token_count":
                    continue
                found_tokens = True
                info = payload.get("info")
                if not isinstance(info, dict) or not isinstance(info.get("total_token_usage"), dict):
                    coverage_complete = False
                    unreadable_usage_events += 1
                    warnings.add(f"{path.name}: token event without supported cumulative counters skipped; coverage incomplete.")
                    continue
                total = info["total_token_usage"]
                snapshot = tuple(counter(total.get(k)) for k in COUNTERS)
                if snapshot in seen_snapshots:
                    continue
                seen_snapshots.add(snapshot)
                usage = {}
                decreasing = False
                for key, current in zip(COUNTERS, snapshot):
                    prior = previous.get(key, 0)
                    if current is None:
                        usage[key] = None
                        previous[key] = None
                    elif prior is None:
                        usage[key] = None
                        previous[key] = current
                    elif current < prior:
                        usage[key] = None
                        decreasing = True
                    else:
                        usage[key] = current - prior
                        previous[key] = current
                if decreasing:
                    warnings.add(f"{path.name}: cumulative counter decreased; affected deltas unknown (possible replay/reset).")
                # Updating the baseline before any filtering is essential.
                if own_start and context_time and context_time < own_start:
                    warnings.add(f"{path.name}: inherited prefix before this session's start excluded.")
                    continue
                event_time = timestamp(event.get("timestamp"))
                if (since or until) and event_time is None:
                    coverage_complete = False
                    warnings.add(f"{path.name}: event with unknown timestamp excluded by time filter.")
                    continue
                if since and event_time < since or until and event_time > until:
                    continue
                tid = context.get("turn_id") or "unknown"
                root_tid = context.get("root_turn_id")
                if turn and turn not in (tid, root_tid):
                    continue
                # A newly supplied optional counter is not another generation.
                if usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
                    continue
                if event_time and (recorded_through is None or event_time > recorded_through):
                    recorded_through = event_time
                model = context.get("model") or "unknown"
                key = (session_id, tid, root_tid, model)
                if key not in rows:
                    rows[key] = {"session_id": session_id, "turn_id": tid, "root_turn_id": root_tid,
                                 "task": tid, "model": model, "usage": dict.fromkeys(COUNTERS, 0),
                                 "usage_events": 0, "priced_events": 0, "unpriced_events": 0,
                                 "priced_subtotal": 0.0, "unpriced_reasons": set(),
                                 "last_usage_at": None,
                                 "known_priced_tokens": 0, "known_unpriced_tokens": 0, "unknown_usage_events": 0}
                row = rows[key]
                if event_time:
                    row["last_usage_at"] = event_time.isoformat()
                row["usage_events"] += 1
                for name, amount in usage.items():
                    row["usage"][name] = None if amount is None or row["usage"][name] is None else row["usage"][name] + amount
                value, reason = price(usage, model, rates)
                known_total = usage["input_tokens"] + usage["output_tokens"] if usage["input_tokens"] is not None and usage["output_tokens"] is not None else None
                if known_total is None:
                    row["unknown_usage_events"] += 1
                if value is None:
                    row["unpriced_events"] += 1
                    row["unpriced_reasons"].add(reason)
                    row["known_unpriced_tokens"] += known_total or 0
                else:
                    row["priced_events"] += 1
                    row["priced_subtotal"] += value
                    row["known_priced_tokens"] += known_total or 0
        if not found_tokens:
            coverage_complete = False
            warnings.add(f"{path.name}: no supported token_count events found; no usage coverage established.")
        if own_start is None:
            warnings.add(f"{path.name}: session start unavailable; inherited history cannot be identified.")
    result_rows = list(rows.values())
    for row in result_rows:
        row["unpriced_reasons"] = sorted(row["unpriced_reasons"])
        row["estimate"] = None if row["unpriced_events"] else row["priced_subtotal"]
    totals = {name: sum(r[name] for r in result_rows) for name in ("usage_events", "priced_events", "unpriced_events", "priced_subtotal", "known_priced_tokens", "known_unpriced_tokens", "unknown_usage_events")}
    totals["estimate"] = None if totals["unpriced_events"] or not totals["usage_events"] else totals["priced_subtotal"]
    totals["unreadable_usage_events"] = unreadable_usage_events
    coverage_complete = coverage_complete and bool(totals["usage_events"]) and not totals["unpriced_events"]
    if not coverage_complete:
        totals["estimate"] = None
    credit_mode = rates and rates.get("billing_mode") == "codex_credits"
    return {"label": "Estimated Standard credits (not actual billed charge)" if credit_mode else "API-equivalent estimate (not actual ChatGPT bill)",
            "currency": rates.get("currency") if rates else None,
            "rates": {k: rates.get(k) for k in ("billing_mode", "verified_at", "source")} if rates else None,
            "recorded_through": recorded_through.isoformat() if recorded_through else None,
            "coverage_complete": coverage_complete,
            "sessions_supplied": session_count, "rows": result_rows, "totals": totals,
            "coverage": "Only explicitly supplied session files and observed cumulative deltas are covered. Distinct sessions are counted separately. Forks may replay inherited history; only prefixes with known pre-session turn timestamps are excluded. Subagents are covered only when their files are supplied. Attribution uses the active turn/model at each usage snapshot; time bounds use snapshot timestamps. Standard credit estimates exclude speed multipliers unless incorporated in the supplied scoped rates. Reasoning tokens are already part of output and are never added again.",
            "warnings": sorted(warnings)}


def render_text(report):
    lines = [report["label"], f"Currency: {report['currency'] or 'unknown (no rates)'}",
             f"Recorded through: {report['recorded_through'] or 'unknown'}; supplied-file estimate coverage complete: {report['coverage_complete']}"]
    if report["rates"]:
        lines.append(f"Rate verification: {report['rates']['verified_at'] or 'unknown'}; source: {report['rates']['source'] or 'unknown'}")
    for row in report["rows"]:
        usage = row["usage"]
        value = "unpriced" if row["estimate"] is None else f"{row['estimate']:.6f}"
        lines.append(f"session={row['session_id']} task/turn={row['turn_id']} root_turn={row['root_turn_id'] or 'unknown'} model={row['model']} input={usage['input_tokens']} cached={usage['cached_input_tokens']} output={usage['output_tokens']} estimate={value}")
        if row["unpriced_reasons"]:
            lines.append("  Unpriced: " + "; ".join(row["unpriced_reasons"]))
    totals = report["totals"]
    subtotal = f"{totals['priced_subtotal']:.6f}" if totals["priced_events"] else "unknown (no priced usage)"
    lines.extend([f"Priced subtotal: {subtotal}; priced snapshots={totals['priced_events']}; unpriced snapshots={totals['unpriced_events']}; known unpriced tokens={totals['known_unpriced_tokens']}; snapshots with unknown usage={totals['unknown_usage_events']}; unreadable usage snapshots={totals['unreadable_usage_events']}", report["coverage"]])
    if not report["rows"]:
        lines.append("No attributable usage in this scope; this does not establish zero cost.")
    lines.extend("Warning: " + message for message in report["warnings"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", action="append", required=True, help="Explicit rollout JSONL path; repeat for scoped subagents")
    parser.add_argument("--turn", help="Match turn_id or root_turn_id")
    parser.add_argument("--since", help="Inclusive timezone-aware ISO timestamp (snapshot time)")
    parser.add_argument("--until", help="Inclusive timezone-aware ISO timestamp (snapshot time)")
    parser.add_argument("--rates", help="Verified exact-model rates JSON, per million tokens")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    since, until = timestamp(args.since), timestamp(args.until)
    if args.since and since is None or args.until and until is None:
        parser.error("time bounds must be ISO timestamps with timezone")
    if since and until and since > until:
        parser.error("--since must be before --until")
    try:
        report = build_report(args.session, load_rates(args.rates), args.turn, since, until)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"task_cost: {exc}\n")
    print(json.dumps(report, indent=2, allow_nan=False) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
