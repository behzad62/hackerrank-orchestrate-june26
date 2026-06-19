# Evaluation Report

## Strategies Compared

| Strategy | Provider | Model | Fresh calls | Cache hits | Fallback rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openrouter-minimax | openrouter | minimax/minimax-m3 | 0 | 20 | 0 | 0.750 | 0.650 | 0.900 | 0.600 | 0.755 | 0.842 | $0.0799 |
| openrouter-gemini | openrouter | google/gemini-3.5-flash | 0 | 20 | 0 | 0.750 | 0.500 | 0.900 | 0.400 | 0.737 | 0.857 | $0.5648 |


## Final Strategy Used For output.csv

- Strategy name: openrouter-gemini
- Provider: openrouter
- Model: google/gemini-3.5-flash
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by FINAL_STRATEGY/--final-strategy.
- Final output command: `python code/main.py --env .env --provider openrouter --model google/gemini-3.5-flash --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 89

### High-Value Field Accuracy

- claim_status: 0.750
- issue_type: 0.500
- object_part: 0.900
- evidence_standard_met: 0.950
- valid_image: 0.850
- severity: 0.400

### All Evaluated Field Accuracy

- evidence_standard_met: 0.950
- evidence_standard_met_reason: 0.000
- risk_flags: 0.450
- issue_type: 0.500
- object_part: 0.900
- claim_status: 0.750
- claim_status_justification: 0.000
- supporting_image_ids: 0.750
- valid_image: 0.850
- severity: 0.400

### Risk Flags

- Precision: 0.677
- Recall: 0.808
- F1: 0.737

### Supporting Image IDs

- Set precision: 0.938
- Set recall: 0.789
- Set F1: 0.857
- Average Jaccard overlap: 0.800

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 1.000
- Average claim justification length: 169.1 chars

## Core Decision Error Analysis

Core decision error count: 49

Core field errors:
- severity: 12
- risk_flags: 11
- issue_type: 10
- claim_status: 5
- supporting_image_ids: 5
- valid_image: 3
- object_part: 2
- evidence_standard_met: 1

Claim status mistakes:
- expected `contradicted`, predicted `supported`: 2
- expected `supported`, predicted `contradicted`: 2
- expected `contradicted`, predicted `not_enough_information`: 1

Issue type mistakes:
- expected `broken_part`, predicted `scratch`: 1
- expected `crack`, predicted `none`: 1
- expected `dent`, predicted `scratch`: 1
- expected `none`, predicted `scratch`: 1
- expected `none`, predicted `torn_packaging`: 1
- expected `scratch`, predicted `none`: 1
- expected `stain`, predicted `water_damage`: 1
- expected `unknown`, predicted `crushed_packaging`: 1
- expected `unknown`, predicted `missing_part`: 1
- expected `unknown`, predicted `none`: 1

Severity mistakes:
- expected `medium`, predicted `high`: 3
- expected `high`, predicted `medium`: 1
- expected `low`, predicted `medium`: 1
- expected `low`, predicted `none`: 1
- expected `low`, predicted `unknown`: 1
- expected `medium`, predicted `low`: 1
- expected `medium`, predicted `none`: 1
- expected `none`, predicted `low`: 1
- expected `none`, predicted `medium`: 1
- expected `unknown`, predicted `none`: 1

Risk flag false positives:
- non_original_image: 3
- claim_mismatch: 2
- manual_review_required: 2
- low_light_or_glare: 1
- wrong_object: 1
- wrong_object_part: 1

Risk flag false negatives:
- damage_not_visible: 4
- claim_mismatch: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- severity: 12
- risk_flags: 11
- issue_type: 10
- claim_status: 5
- supporting_image_ids: 5
- valid_image: 3
- object_part: 2
- evidence_standard_met: 1

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the vehicle is clearly visible, showing severe damage to the rear bumper area and trunk.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `Image img_1 shows severe impact damage to the rear bumper area, including a heavily dented trunk lid and a missing rear bumper cover.`
- Row 1 `severity`: expected `medium`, predicted `high`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 0
- Cache hits: 20
- Fallback rows: 0
- Backup calls: 0
- Prompt tokens: 94746
- Completion tokens: 12734
- Cached/read tokens: 0
- Cache write tokens: 0
- Runtime: 0.08s
- Average latency per token-baseline call: 7.10s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 208441
- Projected output tokens: 28015
- Estimated full-test cost: $0.5648
- Estimated full-test summed provider latency: 312.45s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 236456 tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
- openrouter/google/gemini-3.5-flash: 20 calls, input $1.5000 / 1M, output $9.0000 / 1M
- Price warnings:
- none

## Caching Notes

- Token source: cached provider metadata
- Prompt cache enabled: true
- Response cache ignore mode: false
- Response cache write enabled: true
- If token source is approximate prompt-size estimate, input tokens are estimated from prompt characters and output tokens use the configured max-output budget as a conservative bound.
- Image token usage: provider-specific or unavailable unless provider metadata includes it in prompt token accounting.

## Known Limitations

- No-vision fallback is intentionally conservative and should not be used for final predictions unless explicitly allowed.
- Fallback output does not inspect image content and reports `not_enough_information`.
- AVIF images require a local decoder through `pillow-avif-plugin`; unsupported conversion marks the image unreadable.
- Text found in images is treated as untrusted and can add `text_instruction_present`.
- Free-text justification exact-match scores are kept in all-field metrics, but justification quality is reported separately because exact text does not need to match sample wording.
