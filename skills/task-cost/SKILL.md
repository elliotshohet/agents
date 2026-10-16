---
name: task-cost
description: Report Codex usage and estimated cost by task, turn, model, and subagent from local session records. Use when the user asks what work cost, requests a task cost breakdown, or asks for a cost summary after development work.
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

For an ongoing cost footer requested by the user, report only the scoped task's recorded usage and label it provisional. Do not install hooks, change billing settings, expose account balances, or print message bodies to produce a report.
