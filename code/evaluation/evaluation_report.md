# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-pass-minimax | one_pass | openrouter | minimax/minimax-m3 | same | 0 | 20 | 0 | 0.800 | 0.650 | 0.900 | 0.650 | 0.784 | 0.842 | $0.0894 |
| two-pass-minimax | two_pass | openrouter | minimax/minimax-m3 | openrouter/minimax/minimax-m3 | 4 | 19 | 0 | 0.750 | 0.750 | 0.900 | 0.700 | 0.706 | 0.842 | $0.1524 |


## Final Strategy Used For output.csv

- Strategy name: two-pass-minimax
- Strategy mode: two_pass
- Vision provider: openrouter
- Vision model: minimax/minimax-m3
- Adjudicator: openrouter/minimax/minimax-m3
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by weighted sample score.
- Final output command: `python code/main.py --env .env --provider openrouter --model minimax/minimax-m3 --strategy-mode two_pass --adjudicator-provider openrouter --adjudicator-model minimax/minimax-m3 --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 76

### High-Value Field Accuracy

- claim_status: 0.750
- issue_type: 0.750
- object_part: 0.900
- evidence_standard_met: 0.850
- valid_image: 0.850
- severity: 0.700

### All Evaluated Field Accuracy

- evidence_standard_met: 0.850
- evidence_standard_met_reason: 0.000
- risk_flags: 0.700
- issue_type: 0.750
- object_part: 0.900
- claim_status: 0.750
- claim_status_justification: 0.000
- supporting_image_ids: 0.700
- valid_image: 0.850
- severity: 0.700

### Risk Flags

- Precision: 0.720
- Recall: 0.692
- F1: 0.706

### Supporting Image IDs

- Set precision: 0.842
- Set recall: 0.842
- Set F1: 0.842
- Average Jaccard overlap: 0.775

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 1.000
- Average claim justification length: 265.1 chars

## Core Decision Error Analysis

Core decision error count: 36

Core field errors:
- risk_flags: 6
- severity: 6
- supporting_image_ids: 6
- claim_status: 5
- issue_type: 5
- evidence_standard_met: 3
- valid_image: 3
- object_part: 2

Claim status mistakes:
- expected `contradicted`, predicted `not_enough_information`: 2
- expected `contradicted`, predicted `supported`: 2
- expected `not_enough_information`, predicted `contradicted`: 1

Issue type mistakes:
- expected `broken_part`, predicted `unknown`: 1
- expected `none`, predicted `torn_packaging`: 1
- expected `scratch`, predicted `dent`: 1
- expected `stain`, predicted `water_damage`: 1
- expected `unknown`, predicted `missing_part`: 1

Severity mistakes:
- expected `low`, predicted `medium`: 2
- expected `high`, predicted `unknown`: 1
- expected `low`, predicted `unknown`: 1
- expected `none`, predicted `medium`: 1
- expected `unknown`, predicted `high`: 1

Risk flag false positives:
- damage_not_visible: 2
- wrong_object_part: 2
- low_light_or_glare: 1
- non_original_image: 1
- wrong_angle: 1

Risk flag false negatives:
- claim_mismatch: 3
- damage_not_visible: 2
- cropped_or_obstructed: 1
- wrong_angle: 1
- wrong_object: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 6
- severity: 6
- supporting_image_ids: 6
- claim_status: 5
- issue_type: 5
- evidence_standard_met: 3
- valid_image: 3
- object_part: 2

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the car and the rear bumper are clearly visible from a direct rear angle, allowing assessment of deformation and damage.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `img_1 clearly shows a silver sedan from the rear with significant deformation of the rear bumper cover (partially detached/hanging) and a crumpled/dented trunk lid. The rear bumper area exhibits visible dent and crush damage consistent with the user's claim.`
- Row 2 `evidence_standard_met_reason`: expected `The full front view provides context and the close-up image shows the scratch on the front bumper.`, predicted `img_1 clearly shows the front bumper and headlight area of a white car with visible surface damage; img_2 shows the full front of the same vehicle for context.`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 4
- Cache hits: 19
- Fallback rows: 0
- Backup calls: 0
- Prompt tokens: 139054
- Completion tokens: 22968
- Cached/read tokens: 73628
- Cache write tokens: 0
- Runtime: 89.50s
- Average latency per token-baseline call: 27.52s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 305919
- Projected output tokens: 50530
- Estimated full-test cost: $0.1524
- Estimated full-test summed provider latency: 1211.09s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 356449 tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
- openrouter/minimax/minimax-m3: 23 calls, input $0.3000 / 1M, output $1.2000 / 1M
- Price warnings:
- none

## Caching Notes

- Token source: fresh provider metadata
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
