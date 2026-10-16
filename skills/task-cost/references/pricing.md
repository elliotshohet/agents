# Pricing basis

Official source: https://learn.chatgpt.com/docs/pricing

The packaged rate card was verified on 2026-10-16. Values are credits per million tokens at Standard speed. Codex credit billing has no separate cache-write charge. Cached input is charged at the cached-input rate; remaining input, including cache writes, uses the ordinary input rate.

Use current official OpenAI pricing when available. If using the packaged snapshot, disclose its date rather than claiming it is current. Do not silently map an unfamiliar or versioned model ID to a listed model without authoritative evidence.

Token-derived Standard credits are estimates, not actual subscription allowance consumption or a task-level charge. Purchased-credit Fast mode and Ultrafast mode have different multipliers from included subscription usage. Without verified speed and billing context, report the Standard credit equivalent and state that assumption. Never infer a task's cost from changes in an account-wide credit balance while other work may be running.

API-key usage uses a different rate card: https://developers.openai.com/api/docs/pricing . To report an API-equivalent USD estimate, provide a separate JSON rate card with `currency: "USD"`, `billing_mode: "api_equivalent"`, an official `source`, `verified_at`, and exact-model `input`, `cached_input`, `output`, and when applicable `cache_write_input` prices per million tokens. Apply it only to work whose service tier, context band, caching rules, and other pricing conditions match that card. Split scopes when rates change; do not apply one short-context rate to a mixed-context session.

An API-equivalent estimate is not a statement about the user's actual API invoice. Actual billed cost requires an authoritative billing record attributable to the same task. Separate tool, infrastructure, voice, and image costs require their own recorded usage and applicable rates.
