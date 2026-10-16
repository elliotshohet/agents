---
name: task-cost
description: Report Codex usage and estimated cost by task, turn, model, and subagent from local session records. Use when the user asks what work cost, requests a task cost breakdown, asks for a cost summary after development work, wants automatic usage reporting after each task, or wants a usage percentage footer.
---

# Task Cost

Report recorded token usage and a clearly labeled cost estimate for the requested work. Never present an estimate as an invoice or infer a dollar charge from a ChatGPT subscription allowance.

## Select the work

- Use the current thread unless the user identifies another thread or session. Prefer the exposed `CODEX_THREAD_ID`; do not choose the most recently modified session, which may belong to unrelated parallel work.
- Resolve its rollout and known descendants with `python3 scripts/resolve_sessions.py`. Paths in this skill are relative to the skill directory; run helpers by absolute path when working elsewhere.
- The resolver outputs metadata only. Pass each returned path as a separate `--session` argument to the reporter. Treat its coverage notes as part of the result.
- A thread can contain many tasks. Use `--turn ID` to select a task or report separate turn rows. The filter also matches `root_turn_id` for related subagent work. Use the conversation to give those IDs meaningful task labels when possible; do not invent a mapping from unrelated turns.
- Use `--since` and `--until` only for an explicitly requested time window. The helper reads earlier counters as a baseline before filtering.
- If identity or task boundaries cannot be established, ask only for the missing selection. If detailed usage is unavailable, report that limitation instead of estimating tokens from prompt length, elapsed time, or the aggregate `tokens_used` column.

## Calculate

Run `python3 scripts/task_cost.py --session /absolute/rollout.jsonl --rates references/standard-credit-rates.json`, adding other proven subagent sessions and task filters as needed. Add `--json` for structured output.

The packaged rate card is a dated snapshot of official Standard Codex credit rates. See [pricing guidance](references/pricing.md) before interpreting costs or supplying another rate card.

- Deduplicate cumulative usage snapshots; never add cumulative totals together.
- Cached input is part of input. Reasoning output is part of output. Do not charge either twice.
- Keep models separate when their rates differ. Unknown models and missing or invalid counters remain unpriced, never free.
- Include only subagent sessions with demonstrated parentage. A fork or copied history is not additional new usage merely because it appears in another file. Preserve and disclose helper warnings about inherited history and attribution.
- The helper estimates recorded model-token usage only. Do not imply it includes unrecorded agents, external APIs, cloud infrastructure, voice, image generation, or other tools with separate charges.
- Active work can have delayed usage events. State that results cover recorded usage through the displayed timestamp; the current response's final tokens may not yet be available.

## Present

Use a concise table: task, model, input tokens, cached input tokens, output tokens, estimated credits or cost. Include a priced subtotal and an explicit count of unpriced or unattributed rows. Aggregate related subagent rows into the parent task only when root-turn linkage is proven.

End with a short basis line naming the rate-card date, Standard-speed assumption, last recorded usage timestamp, and material coverage gaps. Show `actual billed amount: unavailable` unless an authoritative task-scoped billing record is supplied. Do not convert credits to USD without a verified applicable purchase rate.

For an ongoing cost footer requested by the user, report only the scoped task's recorded usage and label it provisional. Do not change billing settings, expose account balances, or print message bodies to produce a report.

## Automatic reporting after each task

When the user authorizes automatic reporting, install the skill at a stable path, then run:

```sh
python3 "${CODEX_HOME:-$HOME/.codex}/skills/task-cost/scripts/install_hook.py"
```

The installer merges one command into `${CODEX_HOME:-$HOME/.codex}/hooks.json`, preserves existing hooks and other keys, and makes a private timestamped backup before changing an existing file. Repeating the same installation adds no duplicate. `--codex-home PATH` and `--skill-dir PATH` support explicit locations; use a persistent installed skill directory, never a temporary worktree. It does not edit `config.toml`, notifications, billing, or hook trust records.

Open `/hooks` in Codex to review and trust the exact new hook; reload or start a session if the client has not discovered it. New or changed non-managed hooks are skipped until trusted. Never manufacture trust hashes or bypass this review. Local command hooks require a client that supports them and enabled hooks; this setup does not configure unsupported cloud-orchestrated clients. See the [official hook contract](https://learn.chatgpt.com/docs/hooks).

The `Stop` handler reads the hook's explicit `session_id`, `turn_id`, and `transcript_path`, verifies transcript identity, and resolves only indexed spawn descendants. It reports the selected turn and descendants with matching `root_turn_id`; it never guesses the latest session. Missing identity or unavailable/unsupported counters produce an explicit unavailable result, never a zero-cost inference. A Stop is a completed assistant turn, so a multi-turn task produces separate reports. Interrupted turns do not emit Stop reports.

Each run atomically saves JSON and Markdown under `${CODEX_HOME:-$HOME/.codex}/task-cost/reports/`, with private report permissions. Filenames are a deterministic hash of the session and turn, so a repeated Stop refreshes that turn's report. Reports contain usage metadata and coverage notes, never message bodies. The hook emits only a concise UI `systemMessage`; it makes no model/API calls and never requests continuation or blocks another hook. It does not embed the footer inside the assistant's final message.

Automatic estimates use the packaged dated Standard-speed credit rates and retain all pricing caveats above. They cover recorded usage through the displayed timestamp; delayed final usage, missing descendants, unknown models, and tools with separate charges remain limitations. Review the saved report for coverage notes; actual billed amount remains unavailable.

Verify changes with `python3 -m unittest discover -s scripts -p 'test_*.py'` from the skill directory. Tests use temporary homes and never modify live hooks or trust.

## Minimal usage percentage footer

For the user's default task-end footer, run `python3 scripts/usage_percent.py` from this skill directory (or use its absolute path). It resolves `CODEX_THREAD_ID` and reads only the root thread's latest Codex quota snapshot. `--thread ID`, `--codex-home PATH`, and `--session PATH` support explicit selection. Never select the most recently modified session or print message bodies or account balances.

Append successful output verbatim as the final line of the response, such as `33%` or `33.5%`, without a label or breakdown. This is the account primary allowance-window percentage used as of the latest recorded snapshot, including concurrent work; it is not a task-specific percentage or context-window occupancy. The current response may not yet be reflected. The helper rejects missing, invalid, stale, or expired snapshots with `unavailable` and a nonzero exit. In that case, briefly report unavailability instead of inventing a percentage. No USD rate or credit conversion is needed. Detailed token/cost reports remain available when requested; the percentage footer takes precedence over the detailed presentation for automatic task-end reporting.
