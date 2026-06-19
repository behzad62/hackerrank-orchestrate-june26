# Gemini 3.5 Flash Partial Evaluation

## Configuration

- Provider: `gemini`
- Model: `gemini-3.5-flash`
- Fallback allowed: `false`
- Initial output limit tested: `1800`
- Viable output limit for row 2 smoke test: `4096`
- Implemented follow-up setting: `VLM_REASONING_ENABLED=true`, `VLM_REASONING_EFFORT=low`
- Implemented follow-up retry cap: `VLM_RETRY_MAX_SLEEP_SECONDS=45`

## Result

The full 20-row sample evaluation did not complete because the Google API returned HTTP 429 quota/rate-limit errors for `gemini-3.5-flash`.

Observed behavior:

- With `VLM_MAX_OUTPUT_TOKENS=1800`, row 2 repeatedly finished with `MAX_TOKENS`; the app classified this as `response_truncated`.
- With `VLM_MAX_OUTPUT_TOKENS=4096`, a row 2 smoke test completed successfully.
- A 4096-token full-sample attempt completed 16 rows, then failed with `rate_limited`.
- A later fresh low-thinking attempt failed before row 1 completed because the same quota was still exhausted.

The diagnostic provider error body reported the Google free-tier `generate_content` request quota for model `gemini-3.5-flash`, so this is an account/quota condition rather than an output-schema or image-payload failure.

## Best Partial Run

Best usable fresh run: `2026-06-19T16:33:04Z`

- Completed rows: 16 of 20
- Fresh provider responses: 16
- Images represented by first 16 sample rows: 23
- Provider errors: 6 total
- Error categories: `server_error=1`, `rate_limited=5`
- Prompt tokens: 74,275
- Output tokens: 8,421
- Provider cached input tokens: 8,009
- Provider latency: 217.12s total, 13.57s per completed fresh call

## Cost Projection

Pricing assumption from Google Gemini 3.5 Flash Standard paid tier:

- Input: `$1.50 / 1M tokens`
- Output: `$9.00 / 1M tokens`

Using the 16 completed rows as the basis:

- Average prompt tokens per completed fresh call: 4,642.2
- Average output tokens per completed fresh call: 526.3
- Projected full test rows: 44
- Projected full test input tokens: about 204,256
- Projected full test output tokens: about 23,158
- Projected full test cost: about `$0.5148`
- Projected sequential provider runtime: about 597.1s, excluding quota waits

This projection is less reliable than the Qwen estimate because Gemini did not complete the full sample set.

## Prompt And Runtime Findings

Prompt caching is working at the provider telemetry level when Gemini accepts calls: the 16-row run logged 8,009 cached input tokens. The prompt already follows a cache-friendly structure with stable task rules, schema, evidence requirements, injection policy, and examples before per-claim dynamic data.

The prompt contract is relatively verbose because it asks for `claim_intent`, `visual_observations`, and `decision`. Only `decision` is required by normalization. If Gemini remains truncation-prone or expensive, the next prompt improvement should be an optional decision-only provider contract while preserving the final CSV schema.

The code now exposes global reasoning controls through env config. Google recommends `thinking_level` for Gemini 3.x, and lower values such as `low` or `minimal` are the right next lever for reducing output tokens, latency, and truncation risk.

The retry cap is now configurable with `VLM_RETRY_MAX_SLEEP_SECONDS`. The latest run used sleeps of `1,2,4,8,16,32` seconds before failing on persistent quota exhaustion.

## References

- Gemini 3.5 Flash pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini 3.x parameter guidance: https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5
- Gemini context caching: https://ai.google.dev/gemini-api/docs/caching
