# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | Failed rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| two-pass-gemini-minimax | two_pass | gemini | gemini-3.5-flash | openrouter/minimax/minimax-m3 | 45 | 0 | 0 | 0 | 0.700 | 0.700 | 0.950 | 0.650 | 0.765 | 0.950 | $0.6044 |


Warning: fewer than two real VLM strategies were configured; include another provider/model strategy for a stronger comparison.

## Final Strategy Used For output.csv

- Strategy name: two-pass-gemini-minimax
- Strategy mode: two_pass
- Vision provider: gemini
- Vision model: gemini-3.5-flash
- Adjudicator: openrouter/minimax/minimax-m3
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by FINAL_STRATEGY/--final-strategy.
- Final output command: `python code/main.py --env .env --provider gemini --model gemini-3.5-flash --strategy-mode two_pass --adjudicator-provider openrouter --adjudicator-model minimax/minimax-m3 --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 73

### High-Value Field Accuracy

- claim_status: 0.700
- issue_type: 0.700
- object_part: 0.950
- evidence_standard_met: 0.950
- valid_image: 0.900
- severity: 0.650

### All Evaluated Field Accuracy

- evidence_standard_met: 0.950
- evidence_standard_met_reason: 0.000
- risk_flags: 0.600
- issue_type: 0.700
- object_part: 0.950
- claim_status: 0.700
- claim_status_justification: 0.000
- supporting_image_ids: 0.900
- valid_image: 0.900
- severity: 0.650

### Risk Flags

- Precision: 0.667
- Recall: 0.897
- F1: 0.765

### Supporting Image IDs

- Set precision: 0.950
- Set recall: 0.950
- Set F1: 0.950
- Average Jaccard overlap: 0.950

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 0.950
- Average claim justification length: 173.2 chars

## Core Decision Error Analysis

Core decision error count: 33

Core field errors:
- risk_flags: 8
- severity: 7
- claim_status: 6
- issue_type: 6
- supporting_image_ids: 2
- valid_image: 2
- evidence_standard_met: 1
- object_part: 1

Claim status mistakes:
- expected `supported`, predicted `contradicted`: 4
- expected `contradicted`, predicted `supported`: 1
- expected `not_enough_information`, predicted `contradicted`: 1

Issue type mistakes:
- expected `broken_part`, predicted `scratch`: 1
- expected `crack`, predicted `glass_shatter`: 1
- expected `none`, predicted `scratch`: 1
- expected `scratch`, predicted `dent`: 1
- expected `unknown`, predicted `crushed_packaging`: 1
- expected `water_damage`, predicted `torn_packaging`: 1

Severity mistakes:
- expected `low`, predicted `medium`: 3
- expected `medium`, predicted `high`: 2
- expected `none`, predicted `low`: 1
- expected `unknown`, predicted `low`: 1

Risk flag false positives:
- damage_not_visible: 6
- claim_mismatch: 4
- manual_review_required: 1
- non_original_image: 1
- wrong_object: 1

Risk flag false negatives:
- damage_not_visible: 2
- manual_review_required: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 8
- severity: 7
- claim_status: 6
- issue_type: 6
- supporting_image_ids: 2
- valid_image: 2
- evidence_standard_met: 1
- object_part: 1

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear bumper and trunk area of the vehicle are fully visible, allowing clear assessment of the damage.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `The image img_1 confirms severe denting, deformation, and damage to the rear bumper structure and body panel.`
- Row 2 `evidence_standard_met`: expected `false`, predicted `true`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 45
- Cache hits: 0
- Fallback rows: 0
- Failed rows: 0
- Backup calls: 25
- Prompt tokens: 157272
- Completion tokens: 25586
- Cached/read tokens: 113491
- Cache write tokens: 0
- Runtime: 176.61s
- Average latency per token-baseline call: 9.33s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 345998
- Projected output tokens: 56289
- Estimated full-test cost: $0.6044
- Estimated full-test summed provider latency: 410.48s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 402287 tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
- gemini/gemini-3.5-flash: 20 calls, input $1.5000 / 1M, output $9.0000 / 1M
- openrouter/minimax/minimax-m3: 25 calls, input $0.3000 / 1M, output $1.2000 / 1M
- Price warnings:
- none

## Caching Notes

- Token source: fresh provider metadata
- Prompt cache enabled: true
- Response cache ignore mode: true
- Response cache write enabled: true
- If token source is approximate prompt-size estimate, input tokens are estimated from prompt characters and output tokens use the configured max-output budget as a conservative bound.
- Image token usage: provider-specific or unavailable unless provider metadata includes it in prompt token accounting.

## Known Limitations

- No-vision fallback is intentionally conservative and should not be used for final predictions unless explicitly allowed.
- Fallback output does not inspect image content and reports `not_enough_information`.
- AVIF images require a local decoder through `pillow-avif-plugin`; unsupported conversion marks the image unreadable.
- Text found in images is treated as untrusted and can add `text_instruction_present`.
- Free-text justification exact-match scores are kept in all-field metrics, but justification quality is reported separately because exact text does not need to match sample wording.
