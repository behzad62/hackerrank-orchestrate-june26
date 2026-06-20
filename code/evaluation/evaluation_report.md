# Evaluation Report

## Strategies Compared

| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | Failed rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| one-pass-minimax | one_pass | openrouter | minimax/minimax-m3 | same | 0 | 20 | 0 | 0 | 0.650 | 0.550 | 0.850 | 0.600 | 0.780 | 0.833 | $0.0823 |
| two-pass-minimax | two_pass | openrouter | minimax/minimax-m3 | openrouter/minimax/minimax-m3 | 0 | 20 | 0 | 0 | 0.750 | 0.500 | 0.900 | 0.600 | 0.688 | 0.811 | $0.1720 |
| two-pass-gemini-minimax | two_pass | openrouter | google/gemini-3.5-flash | openrouter/minimax/minimax-m3 | 0 | 20 | 0 | 0 | 0.850 | 0.950 | 1.000 | 0.900 | 0.862 | 1.000 | $0.1920 |


## Final Strategy Used For output.csv

- Strategy name: two-pass-gemini-minimax
- Strategy mode: two_pass
- Vision provider: openrouter
- Vision model: google/gemini-3.5-flash
- Adjudicator: openrouter/minimax/minimax-m3
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by weighted sample score.
- Final output command: `python code/main.py --env .env --provider openrouter --model google/gemini-3.5-flash --strategy-mode two_pass --adjudicator-provider openrouter --adjudicator-model minimax/minimax-m3 --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 51

### High-Value Field Accuracy

- claim_status: 0.850
- issue_type: 0.950
- object_part: 1.000
- evidence_standard_met: 0.950
- valid_image: 1.000
- severity: 0.900

### All Evaluated Field Accuracy

- evidence_standard_met: 0.950
- evidence_standard_met_reason: 0.000
- risk_flags: 0.800
- issue_type: 0.950
- object_part: 1.000
- claim_status: 0.850
- claim_status_justification: 0.000
- supporting_image_ids: 1.000
- valid_image: 1.000
- severity: 0.900

### Risk Flags

- Precision: 0.778
- Recall: 0.966
- F1: 0.862

### Supporting Image IDs

- Set precision: 1.000
- Set recall: 1.000
- Set F1: 1.000
- Average Jaccard overlap: 1.000

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 0.950
- Average claim justification length: 191.9 chars

## Core Decision Error Analysis

Core decision error count: 11

Core field errors:
- risk_flags: 4
- claim_status: 3
- severity: 2
- evidence_standard_met: 1
- issue_type: 1

Claim status mistakes:
- expected `supported`, predicted `contradicted`: 2
- expected `supported`, predicted `not_enough_information`: 1

Issue type mistakes:
- expected `scratch`, predicted `dent`: 1

Severity mistakes:
- expected `low`, predicted `medium`: 1
- expected `medium`, predicted `unknown`: 1

Risk flag false positives:
- claim_mismatch: 3
- damage_not_visible: 2
- wrong_object: 2
- manual_review_required: 1

Risk flag false negatives:
- manual_review_required: 1

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 4
- claim_status: 3
- severity: 2
- evidence_standard_met: 1
- issue_type: 1

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `The rear of the vehicle is clearly visible, allowing for a complete assessment of the bumper and trunk area.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `Image img_1 shows severe damage to the rear of the vehicle, where the rear bumper cover is completely missing and the underlying bumper structure is heavily crushed and deformed.`
- Row 2 `evidence_standard_met_reason`: expected `The close-up image shows front-end damage, but the full-view image appears to show a different car, so the image set does not satisfy vehicle identity evidence.`, predicted `The images show two completely different vehicles, allowing for a clear determination of a claim mismatch.`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 0
- Cache hits: 20
- Fallback rows: 0
- Failed rows: 0
- Backup calls: 0
- Prompt tokens: 143557
- Completion tokens: 36847
- Cached/read tokens: 35382
- Cache write tokens: 2155
- Runtime: 0.10s
- Average latency per token-baseline call: 30.10s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 315825
- Projected output tokens: 81063
- Estimated full-test cost: $0.1920
- Estimated full-test summed provider latency: 1324.19s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 396888 tokens across the projected full test; divide by intended runtime minutes for required TPM.
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
