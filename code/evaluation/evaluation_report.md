# Evaluation Report

## Strategy

- Provider configured: `none`
- Provider observed in sample run: `none`
- Model: `none`
- Fallback allowed: `True`
- Fallback actually used/no-vision: `True`
- Fallback honesty: No VLM provider was configured, so images were not inspected and model cost is $0.

## Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 186

### High-Value Field Accuracy

- claim_status: 0.100
- issue_type: 0.150
- object_part: 0.050
- evidence_standard_met: 0.100
- valid_image: 0.100
- severity: 0.100

### All Evaluated Field Accuracy

- evidence_standard_met: 0.100
- evidence_standard_met_reason: 0.000
- risk_flags: 0.000
- issue_type: 0.150
- object_part: 0.050
- claim_status: 0.100
- claim_status_justification: 0.000
- supporting_image_ids: 0.100
- valid_image: 0.100
- severity: 0.100

### Risk Flags

- Precision: 0.500
- Recall: 0.500
- F1: 0.500

### Supporting Image IDs

- Set precision: 1.000
- Set recall: 0.000
- Set F1: 0.000
- Average Jaccard overlap: 0.100

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Model calls: 0

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 0

The system uses one multimodal call per claim row when a real VLM provider is configured. Images for the same claim are submitted together so the model can compare overview and close-up evidence.

Pricing assumptions:
- Provider pricing varies by selected model.
- Use provider token accounting from logs/provider metadata when available.
- Input token price assumption: $0.0000 / 1M tokens.
- Output token price assumption: $0.0000 / 1M tokens.
- With `VLM_PROVIDER=none`, images were not inspected and model cost is $0.
- If fallback is observed during a real-provider run, fallback rows did not receive visual inspection; provider rows may still have token costs.

Observed token usage:
- Observed prompt tokens: 0
- Observed output tokens: 0
- Observed average prompt tokens per fresh call: 0.0
- Observed average output tokens per fresh call: 0.0

Estimated full-test token usage and cost:
- Projected input tokens: 0
- Projected output tokens: 0
- Estimated full-test cost: $0.0000

Latency/runtime estimate:
- Observed total provider latency: 0.00s
- Observed average latency per fresh call: 0.00s
- Estimated full-test provider runtime at current sequential settings: 0.00s

Runtime and rate limits:
- Calls are sequential by default.
- RPM consideration: sequential execution targets at most one in-flight provider request, so effective RPM is bounded by provider latency and retry backoff rather than local parallelism.
- TPM consideration: projected full-test token volume is approximately 0 total tokens; configure provider TPM limits above this divided by the intended runtime window.
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
