# Model Comparison Notes

## Completed Baseline: OpenRouter Qwen 3.7 Plus

- Provider/model: `openrouter` / `qwen/qwen3.7-plus`
- Sample rows completed: 20 of 20
- Sample images: 29
- Model calls: 20
- Prompt tokens: 77,304
- Output tokens: 18,886
- Provider latency: 410.05s total, 20.50s per fresh call
- Projected full-test rows/images: 44 rows, 82 images
- Projected full-test cost: about `$0.1076` using `$0.32 / 1M` input and `$1.28 / 1M` output

Quality metrics:

- `claim_status`: 0.700
- `issue_type`: 0.500
- `object_part`: 0.900
- `evidence_standard_met`: 0.850
- `valid_image`: 0.950
- `severity`: 0.400
- Risk flags F1: 0.578
- Supporting image IDs F1: 0.889

Note: this archived Qwen run predates the later OpenRouter cache-control alignment, so it is usable as a quality/cost baseline but should be rerun before treating cache telemetry as final.

## Partial Candidate: Native Gemini 3.5 Flash

- Provider/model: `gemini` / `gemini-3.5-flash`
- Full sample status: incomplete due to Google HTTP 429 quota/rate-limit errors
- Best partial rows completed: 16 of 20
- Fresh calls in best partial run: 16
- Prompt tokens in best partial run: 74,275
- Output tokens in best partial run: 8,421
- Provider cached input tokens logged: 8,009
- Provider latency in best partial run: 217.12s total, 13.57s per completed fresh call
- Projected full-test cost: about `$0.5148` using `$1.50 / 1M` input and `$9.00 / 1M` output
- Projected sequential provider runtime: about 597.1s, excluding quota waits

Gemini quality cannot be compared yet because it did not complete the 20-row sample. The partial run did show lower output-token use and faster completed-call latency than the Qwen run, but the account-level quota prevented a defensible quality score.

## Current Recommendation

Use the Qwen run as the current complete evaluation baseline.

For the next Gemini attempt, use:

- `VLM_PROVIDER=gemini`
- `VLM_MODEL=gemini-3.5-flash`
- `VLM_MAX_OUTPUT_TOKENS=4096`
- `VLM_REASONING_ENABLED=true`
- `VLM_REASONING_EFFORT=low`
- `VLM_REASONING_EXCLUDE=true`
- `VLM_MAX_RETRIES=6`
- `VLM_RETRY_MAX_SLEEP_SECONDS=45`
- a fresh `VLM_CACHE_DIR` for any apples-to-apples rerun

Prompt improvement candidates:

- Add a provider-contract mode that asks only for the `decision` object, since normalization does not require `claim_intent` or `visual_observations`.
- Keep the current stable-prefix ordering for provider prompt caching.
- Preserve the prompt-injection and text-in-image rules exactly; they are part of the submission behavior, not an optimization target.
- Rerun Qwen after the OpenRouter cache-control fix before final model selection.

References:

- Gemini 3.5 Flash pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini 3.x parameter guidance: https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5
- Gemini context caching: https://ai.google.dev/gemini-api/docs/caching
