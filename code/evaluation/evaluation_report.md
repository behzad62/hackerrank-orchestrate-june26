# Evaluation Report

## Strategy

- Provider configured: `openrouter`
- Provider observed in sample run: `mixed:gemini;openrouter`
- Model: `minimax/minimax-m3`
- Fallback allowed: `False`
- Fallback actually used/no-vision: `False`
- Fallback honesty: A configured VLM provider was used for image inspection.

## Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 93

### High-Value Field Accuracy

- claim_status: 0.700
- issue_type: 0.400
- object_part: 0.900
- evidence_standard_met: 0.800
- valid_image: 0.900
- severity: 0.450

### All Evaluated Field Accuracy

- claim_status: 0.700
- claim_status_justification: 0.000
- evidence_standard_met: 0.800
- evidence_standard_met_reason: 0.000
- issue_type: 0.400
- object_part: 0.900
- risk_flags: 0.500
- severity: 0.450
- supporting_image_ids: 0.700
- valid_image: 0.900

### Risk Flags

- Precision: 0.579
- Recall: 0.423
- F1: 0.489

### Supporting Image IDs

- Set precision: 0.875
- Set recall: 0.737
- Set F1: 0.800
- Average Jaccard overlap: 0.725

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Model calls: 36
- Primary provider calls: 18
- Backup provider calls: 18
- Fallback rows: 0
- Cache hits: 0
- Configured max concurrency: 1
- Rate-limit waits: 0

Backup reasons:
- rate_limited: 18

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 79

The system uses one multimodal call per claim row when a real VLM provider is configured. Images for the same claim are submitted together so the model can compare overview and close-up evidence.

Pricing assumptions:
- Provider pricing varies by selected model.
- Use provider token accounting from logs/provider metadata when available.
- Unlisted model input price default: $0.0000 / 1M tokens.
- Unlisted model output price default: $0.0000 / 1M tokens.
- Model-specific price assumptions:
- openrouter/qwen/qwen3.7-plus: 18 calls, input $0.3200 / 1M, output $1.2800 / 1M
- With `VLM_PROVIDER=none`, images were not inspected and model cost is $0.
- If fallback is observed during a real-provider run, fallback rows did not receive visual inspection; provider rows may still have token costs.

Observed token usage:
- Observed prompt tokens: 65963
- Observed output tokens: 16964
- Observed prompt cache write tokens: 0
- Observed prompt cache read tokens: 34884
- Observed prompt cache hit ratio: 0.529
- Observed average prompt tokens per fresh call: 3664.6
- Observed average output tokens per fresh call: 942.4

Estimated full-test token usage and cost:
- Projected input tokens: 145119
- Projected output tokens: 37321
- Estimated full-test cost: $0.0942

Latency/runtime estimate:
- Observed total provider latency: 353.17s
- Observed total run runtime: 0.00s
- Observed average latency per fresh call: 19.62s
- Estimated full-test provider runtime at current sequential settings: 1550.01s

Runtime and rate limits:
- Calls are sequential by default.
- RPM consideration: sequential execution targets at most one in-flight provider request, so effective RPM is bounded by provider latency and retry backoff rather than local parallelism.
- TPM consideration: projected full-test token volume is approximately 182440 total tokens; configure provider TPM limits above this divided by the intended runtime window.
- Retry policy uses bounded retries for rate limits, server errors, timeouts, truncated responses, and JSON parse errors.
- Cache keys include provider, model, prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Caching and batching:
- Successful provider responses are cached by stable content hash.
- Fallback results after provider errors are not cached as successful model evidence.
- Rows are not batched across claims; image sets are grouped per claim.

Known limitations:
- No-vision fallback is intentionally conservative and should not be used for final predictions unless explicitly allowed.
- Fallback output does not inspect image content and therefore reports `not_enough_information`.
- AVIF images require a local decoder through `pillow-avif-plugin`; unsupported conversion marks the image unreadable.
- Text found in images is treated as untrusted and can add `text_instruction_present`.

Failure modes observed in logs:
- Review `logs/run.jsonl` for provider error categories, retry counts, cache hits, and normalization repairs.
