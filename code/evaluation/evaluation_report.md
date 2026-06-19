# Evaluation Report

## Strategy

- Provider configured: `openrouter`
- Provider observed in sample run: `openrouter`
- Model: `minimax/minimax-m3`
- Fallback allowed: `False`
- Fallback actually used/no-vision: `False`
- Fallback honesty: No fresh provider calls were made in this run. Results came from cached provider output, so any visual inspection occurred in the earlier run that populated the cache.

## Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 100

### High-Value Field Accuracy

- claim_status: 0.700
- issue_type: 0.450
- object_part: 0.800
- evidence_standard_met: 0.750
- valid_image: 0.750
- severity: 0.450

### All Evaluated Field Accuracy

- evidence_standard_met: 0.750
- evidence_standard_met_reason: 0.000
- risk_flags: 0.500
- issue_type: 0.450
- object_part: 0.800
- claim_status: 0.700
- claim_status_justification: 0.000
- supporting_image_ids: 0.600
- valid_image: 0.750
- severity: 0.450

### Risk Flags

- Precision: 0.714
- Recall: 0.577
- F1: 0.638

### Supporting Image IDs

- Set precision: 0.812
- Set recall: 0.684
- Set F1: 0.743
- Average Jaccard overlap: 0.650

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Model calls: 0
- Primary provider calls: 0
- Backup provider calls: 0
- Fallback rows: 0
- Cache hits: 20
- Configured max concurrency: 3
- Rate-limit waits: 0

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44

The system uses one multimodal call per claim row when a real VLM provider is configured. Images for the same claim are submitted together so the model can compare overview and close-up evidence.

Pricing assumptions:
- Provider pricing varies by selected model.
- Use provider token accounting from logs/provider metadata when available.
- Unlisted model input price default: $0.0000 / 1M tokens.
- Unlisted model output price default: $0.0000 / 1M tokens.
- Model-specific price assumptions:
- none observed in this run
- With `VLM_PROVIDER=none`, images were not inspected and model cost is $0.
- If fallback is observed during a real-provider run, fallback rows did not receive visual inspection; provider rows may still have token costs.

Observed token usage:
- Observed prompt tokens: 0
- Observed output tokens: 0
- Observed prompt cache write tokens: 0
- Observed prompt cache read tokens: 0
- Observed prompt cache hit ratio: 0.000
- Observed average prompt tokens per fresh call: 0.0
- Observed average output tokens per fresh call: 0.0

Estimated full-test token usage and cost:
- Projected input tokens: unavailable (sample run had no fresh provider calls)
- Projected output tokens: unavailable (sample run had no fresh provider calls)
- Estimated full-test cost: unavailable (sample run had no fresh token baseline)

Latency/runtime estimate:
- Observed total provider latency: unavailable (sample run had no fresh provider calls)
- Observed total run runtime: 0.16s
- Observed average latency per fresh call: unavailable (sample run had no fresh provider calls)
- Estimated full-test summed provider latency at current settings: unavailable (sample run had no fresh latency baseline)

Runtime and rate limits:
- Calls use bounded parallel execution with up to 3 in-flight provider requests.
- RPM consideration: local parallelism can increase burst pressure; the configured RPM limiter, retry backoff, and provider latency bound request rate.
- TPM consideration: projected token volume is unavailable because the sample run had no fresh provider calls; run one uncached sample pass or use provider pricing/token metadata before final cost planning.
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
