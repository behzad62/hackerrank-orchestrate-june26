# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | Failed rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-pass-minimax | one_pass | openrouter | minimax/minimax-m3 | same | 21 | 0 | 0 | 0 | 0.700 | 0.550 | 0.900 | 0.650 | 0.691 | 0.788 | $0.0990 |
| two-pass-minimax | two_pass | openrouter | minimax/minimax-m3 | openrouter/minimax/minimax-m3 | 53 | 0 | 0 | 0 | 0.700 | 0.700 | 0.850 | 0.600 | 0.846 | 0.774 | $0.1692 |


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
- Error count: 88

### High-Value Field Accuracy

- claim_status: 0.700
- issue_type: 0.700
- object_part: 0.850
- evidence_standard_met: 0.700
- valid_image: 0.650
- severity: 0.600

### All Evaluated Field Accuracy

- evidence_standard_met: 0.700
- evidence_standard_met_reason: 0.000
- risk_flags: 0.700
- issue_type: 0.700
- object_part: 0.850
- claim_status: 0.700
- claim_status_justification: 0.000
- supporting_image_ids: 0.700
- valid_image: 0.650
- severity: 0.600

### Risk Flags

- Precision: 0.846
- Recall: 0.846
- F1: 0.846

### Supporting Image IDs

- Set precision: 1.000
- Set recall: 0.632
- Set F1: 0.774
- Average Jaccard overlap: 0.700

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 1.000
- Average claim justification length: 215.1 chars

## Core Decision Error Analysis

Core decision error count: 48

Core field errors:
- severity: 8
- valid_image: 7
- claim_status: 6
- evidence_standard_met: 6
- issue_type: 6
- risk_flags: 6
- supporting_image_ids: 6
- object_part: 3

Claim status mistakes:
- expected `contradicted`, predicted `not_enough_information`: 3
- expected `supported`, predicted `not_enough_information`: 3

Issue type mistakes:
- expected `broken_part`, predicted `unknown`: 2
- expected `crack`, predicted `unknown`: 1
- expected `none`, predicted `unknown`: 1
- expected `scratch`, predicted `unknown`: 1
- expected `stain`, predicted `unknown`: 1

Severity mistakes:
- expected `medium`, predicted `unknown`: 3
- expected `low`, predicted `unknown`: 2
- expected `high`, predicted `unknown`: 1
- expected `low`, predicted `medium`: 1
- expected `none`, predicted `unknown`: 1

Risk flag false positives:
- blurry_image: 1
- damage_not_visible: 1
- low_light_or_glare: 1
- wrong_object: 1

Risk flag false negatives:
- damage_not_visible: 2
- claim_mismatch: 1
- cropped_or_obstructed: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- severity: 8
- valid_image: 7
- claim_status: 6
- evidence_standard_met: 6
- issue_type: 6
- risk_flags: 6
- supporting_image_ids: 6
- object_part: 3

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the car and the rear bumper are clearly visible from a direct rear angle, allowing inspection of deformation. The dent/crush damage on the rear bumper is plainly observable.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `img_1 shows the rear of a white car with obvious deformation of the rear bumper cover — the panel is crushed inward across a wide horizontal band, with the lower section hanging/buckled and exposed structure beneath. The trunk lid also shows denting along its top edge. The claimed dent on the rear bumper is clearly visible.`
- Row 2 `evidence_standard_met_reason`: expected `The full front view provides context and the close-up image shows the scratch on the front bumper.`, predicted `img_1 provides a close-up view of the front bumper showing visible scratches/scrapes, sufficient to evaluate the claim.`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 53
- Cache hits: 0
- Fallback rows: 0
- Failed rows: 0
- Backup calls: 0
- Prompt tokens: 150668
- Completion tokens: 26406
- Cached/read tokens: 56033
- Cache write tokens: 0
- Runtime: 229.37s
- Average latency per token-baseline call: 11.29s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 331470
- Projected output tokens: 58093
- Estimated full-test cost: $0.1692
- Estimated full-test summed provider latency: 496.88s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 389563 tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
- openrouter/minimax/minimax-m3: 53 calls, input $0.3000 / 1M, output $1.2000 / 1M
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
