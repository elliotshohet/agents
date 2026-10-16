# Pricing basis

Official source: https://learn.chatgpt.com/docs/pricing

The packaged rate card was verified on 2026-10-16. Values are credits per million tokens at Standard speed. Codex credit billing has no separate cache-write charge. Cached input is charged at the cached-input rate; remaining input, including cache writes, uses the ordinary input rate.

Use current official OpenAI pricing when available. If using the packaged snapshot, disclose its date rather than claiming it is current. Do not silently map an unfamiliar or versioned model ID to a listed model without authoritative evidence.

Token-derived Standard credits are estimates, not actual subscription allowance consumption or a task-level charge. Purchased-credit Fast mode and Ultrafast mode have different multipliers from included subscription usage. Without verified speed and billing context, report the Standard credit equivalent and state that assumption. Never infer a task's cost from changes in an account-wide credit balance while other work may be running.

API-key usage uses a different rate card: https://developers.openai.com/api/docs/pricing . To report an API-equivalent USD estimate, provide a separate JSON rate card with `currency: "USD"`, `billing_mode: "api_equivalent"`, an official `source`, `verified_at`, and exact-model `input`, `cached_input`, `output`, and when applicable `cache_write_input` prices per million tokens. Apply it only to work whose service tier, context band, caching rules, and other pricing conditions match that card. Split scopes when rates change; do not apply one short-context rate to a mixed-context session.

An API-equivalent estimate is not a statement about the user's actual API invoice. Actual billed cost requires an authoritative billing record attributable to the same task. Separate tool, infrastructure, voice, and image costs require their own recorded usage and applicable rates.

## Default USD estimates

The user's default for hook estimates is the packaged `standard-usd-rates.json`: Standard API-equivalent model pricing, verified 2026-10-16, with short/long-context rates for the listed exact model IDs. No purchased-credit conversion is needed. The model-token estimate includes uncached input, cached input, recorded cache writes, and output (including reasoning). Requests above 272,000 input tokens use the long-context rates. If a combined snapshot cannot establish its applicable context band, leave it unpriced. Unknown model IDs never inherit a guessed model's rate.

Overrides use a complete USD rate-card JSON supplied with the hook's `--rates PATH`, the installer's `--rates PATH`, or `TASK_COST_RATES`. Standard assumes no Fast/Ultrafast multiplier, Batch/Flex discount, or regional premium unless the override supplies those applicable rates. This intentionally estimates model-token usage only; external APIs, separately billed tools, infrastructure, voice, and generated images need separate usage records. Raw UI dollar amounts are provisional estimates; detailed local reports retain their date, assumptions, coverage gaps, and the fact that actual billed charges are unavailable.

Sources: [API pricing](https://developers.openai.com/api/docs/pricing), [GPT-6.1 Sol context pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
