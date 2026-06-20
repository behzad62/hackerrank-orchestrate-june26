# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | Failed rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-pass-minimax | one_pass | openrouter | minimax/minimax-m3 | same | 30 | 0 | 0 | 0 | 0.650 | 0.600 | 0.800 | 0.650 | 0.655 | 0.789 | $0.0576 |
| two-pass-minimax | two_pass | openrouter | minimax/minimax-m3 | openrouter/minimax/minimax-m3 | 42 | 0 | 0 | 0 | 0.900 | 0.750 | 0.950 | 0.800 | 0.772 | 0.950 | $0.1796 |
| two-pass-gemini-minimax | two_pass | openrouter | google/gemini-3.5-flash | openrouter/minimax/minimax-m3 | 41 | 0 | 0 | 0 | 0.850 | 0.800 | 1.000 | 0.850 | 0.836 | 1.000 | $0.9649 |


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
- Reason selected: Selected by FINAL_STRATEGY/--final-strategy.
- Final output command: `python code/main.py --env .env --provider openrouter --model minimax/minimax-m3 --strategy-mode one_pass --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 90

### High-Value Field Accuracy

- claim_status: 0.650
- issue_type: 0.600
- object_part: 0.800
- evidence_standard_met: 0.800
- valid_image: 0.800
- severity: 0.650

### All Evaluated Field Accuracy

- evidence_standard_met: 0.800
- evidence_standard_met_reason: 0.000
- risk_flags: 0.500
- issue_type: 0.600
- object_part: 0.800
- claim_status: 0.650
- claim_status_justification: 0.000
- supporting_image_ids: 0.700
- valid_image: 0.800
- severity: 0.650

### Risk Flags

- Precision: 0.655
- Recall: 0.655
- F1: 0.655

### Supporting Image IDs

- Set precision: 0.833
- Set recall: 0.750
- Set F1: 0.789
- Average Jaccard overlap: 0.725

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 0.950
- Average claim justification length: 207.9 chars

## Core Decision Error Analysis

Core decision error count: 50

Core field errors:
- risk_flags: 10
- issue_type: 8
- claim_status: 7
- severity: 7
- supporting_image_ids: 6
- evidence_standard_met: 4
- object_part: 4
- valid_image: 4

Claim status mistakes:
- expected `contradicted`, predicted `supported`: 2
- expected `supported`, predicted `not_enough_information`: 2
- expected `contradicted`, predicted `not_enough_information`: 1
- expected `not_enough_information`, predicted `contradicted`: 1
- expected `supported`, predicted `contradicted`: 1

Issue type mistakes:
- expected `broken_part`, predicted `unknown`: 2
- expected `crack`, predicted `unknown`: 1
- expected `crushed_packaging`, predicted `unknown`: 1
- expected `none`, predicted `scratch`: 1
- expected `scratch`, predicted `dent`: 1
- expected `unknown`, predicted `crushed_packaging`: 1
- expected `unknown`, predicted `missing_part`: 1

Severity mistakes:
- expected `low`, predicted `medium`: 2
- expected `medium`, predicted `unknown`: 2
- expected `high`, predicted `unknown`: 1
- expected `none`, predicted `low`: 1
- expected `unknown`, predicted `high`: 1

Risk flag false positives:
- damage_not_visible: 5
- claim_mismatch: 3
- non_original_image: 1
- wrong_object: 1

Risk flag false negatives:
- claim_mismatch: 3
- damage_not_visible: 2
- wrong_object: 2
- cropped_or_obstructed: 1
- manual_review_required: 1
- non_original_image: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 10
- issue_type: 8
- claim_status: 7
- severity: 7
- supporting_image_ids: 6
- evidence_standard_met: 4
- object_part: 4
- valid_image: 4

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the car is clearly visible from a direct rear angle, showing the rear bumper and surrounding bodywork in sufficient detail to assess damage.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `Image img_1 clearly shows the rear of a white car with severe deformation and crushing damage to the rear bumper area, including a visibly dented trunk lid and a crushed/displaced rear bumper. This directly supports the user's claim of new damage to the rear bumper.`
- Row 2 `evidence_standard_met_reason`: expected `The close-up image shows front-end damage, but the full-view image appears to show a different car, so the image set does not satisfy vehicle identity evidence.`, predicted `No visual evidence content was provided in the provider output to assess the claimed front bumper scratch.`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 30
- Cache hits: 0
- Fallback rows: 0
- Failed rows: 0
- Backup calls: 0
- Prompt tokens: 47145
- Completion tokens: 10050
- Cached/read tokens: 10354
- Cache write tokens: 0
- Runtime: 150.10s
- Average latency per token-baseline call: 9.56s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 103719
- Projected output tokens: 22110
- Estimated full-test cost: $0.0576
- Estimated full-test summed provider latency: 420.81s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 125829 tokens across the projected full test; divide by intended runtime minutes for required TPM.
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
