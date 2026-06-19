# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-pass-minimax | one_pass | openrouter | minimax/minimax-m3 | same | 22 | 0 | 0 | 0.900 | 0.600 | 0.800 | 0.600 | 0.750 | 0.889 | $0.1011 |
| two-pass-minimax | two_pass | openrouter | minimax/minimax-m3 | openrouter/minimax/minimax-m3 | 40 | 0 | 0 | 0.800 | 0.500 | 0.900 | 0.550 | 0.657 | 0.824 | $0.1590 |
| two-pass-gemini-minimax | two_pass | gemini | gemini-3.5-flash | openrouter/minimax/minimax-m3 | 41 | 0 | 0 | 0.650 | 0.450 | 0.850 | 0.450 | 0.700 | 0.833 | $0.4992 |


## Final Strategy Used For output.csv

- Strategy name: one-pass-minimax
- Strategy mode: one_pass
- Vision provider: openrouter
- Vision model: minimax/minimax-m3
- Adjudicator: same as vision model
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by weighted sample score.
- Final output command: `python code/main.py --env .env --provider openrouter --model minimax/minimax-m3 --strategy-mode one_pass --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 80

### High-Value Field Accuracy

- claim_status: 0.900
- issue_type: 0.600
- object_part: 0.800
- evidence_standard_met: 0.950
- valid_image: 0.800
- severity: 0.600

### All Evaluated Field Accuracy

- evidence_standard_met: 0.950
- evidence_standard_met_reason: 0.000
- risk_flags: 0.550
- issue_type: 0.600
- object_part: 0.800
- claim_status: 0.900
- claim_status_justification: 0.000
- supporting_image_ids: 0.800
- valid_image: 0.800
- severity: 0.600

### Risk Flags

- Precision: 0.700
- Recall: 0.808
- F1: 0.750

### Supporting Image IDs

- Set precision: 0.941
- Set recall: 0.842
- Set F1: 0.889
- Average Jaccard overlap: 0.850

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 0.950
- Average claim justification length: 317.1 chars

## Core Decision Error Analysis

Core decision error count: 40

Core field errors:
- risk_flags: 9
- issue_type: 8
- severity: 8
- object_part: 4
- supporting_image_ids: 4
- valid_image: 4
- claim_status: 2
- evidence_standard_met: 1

Claim status mistakes:
- expected `contradicted`, predicted `supported`: 1
- expected `supported`, predicted `not_enough_information`: 1

Issue type mistakes:
- expected `broken_part`, predicted `scratch`: 1
- expected `none`, predicted `torn_packaging`: 1
- expected `scratch`, predicted `dent`: 1
- expected `stain`, predicted `water_damage`: 1
- expected `torn_packaging`, predicted `crushed_packaging`: 1
- expected `unknown`, predicted `crack`: 1
- expected `unknown`, predicted `crushed_packaging`: 1
- expected `unknown`, predicted `missing_part`: 1

Severity mistakes:
- expected `medium`, predicted `low`: 3
- expected `high`, predicted `medium`: 1
- expected `low`, predicted `high`: 1
- expected `low`, predicted `medium`: 1
- expected `low`, predicted `unknown`: 1
- expected `none`, predicted `medium`: 1

Risk flag false positives:
- damage_not_visible: 2
- blurry_image: 1
- claim_mismatch: 1
- low_light_or_glare: 1
- non_original_image: 1
- wrong_angle: 1
- wrong_object: 1
- wrong_object_part: 1

Risk flag false negatives:
- damage_not_visible: 3
- claim_mismatch: 1
- cropped_or_obstructed: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 9
- issue_type: 8
- severity: 8
- object_part: 4
- supporting_image_ids: 4
- valid_image: 4
- claim_status: 2
- evidence_standard_met: 1

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the car and the claimed rear bumper are clearly visible from a direct rear angle, allowing assessment of surface deformation and structural damage.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `Image img_1 clearly shows the rear of a white car with significant deformation of the rear bumper. The bumper cover is crushed inward, partially detached, and the lower valance area is pushed in exposing the underlying structure. The trunk lid also shows visible deformation. The claim of a new dent on the rear bumper is visually supported.`
- Row 1 `severity`: expected `medium`, predicted `low`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 22
- Cache hits: 0
- Fallback rows: 0
- Backup calls: 0
- Prompt tokens: 82665
- Completion tokens: 17637
- Cached/read tokens: 57486
- Cache write tokens: 0
- Runtime: 176.50s
- Average latency per token-baseline call: 22.51s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 181863
- Projected output tokens: 38801
- Estimated full-test cost: $0.1011
- Estimated full-test summed provider latency: 990.61s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 220664 tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
- openrouter/minimax/minimax-m3: 20 calls, input $0.3000 / 1M, output $1.2000 / 1M
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
