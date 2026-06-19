# Evaluation Report

## Strategies Compared

| Strategy | Provider | Model | Fresh calls | Cache hits | Fallback rows | claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openrouter-minimax | openrouter | minimax/minimax-m3 | 20 | 0 | 0 | 0.750 | 0.500 | 0.850 | 0.500 | 0.577 | 0.842 | $0.0953 |
| openrouter-qwen3.7 | openrouter | qwen/qwen3.7-plus | 20 | 0 | 0 | 0.750 | 0.450 | 0.900 | 0.400 | 0.512 | 0.833 | $0.1079 |


## Final Strategy Used For output.csv

- Strategy name: openrouter-minimax
- Provider: openrouter
- Model: minimax/minimax-m3
- Backup chain: openrouter:minimax/minimax-m3
- Fallback allowed for final: false
- Max concurrency: 3
- RPM limit: 60
- Prompt cache: enabled
- Reason selected: Selected by FINAL_STRATEGY/--final-strategy.
- Final output command: `python code/main.py --env .env --provider openrouter --model minimax/minimax-m3 --no-fallback`

## Final Strategy Sample Metrics

- Rows expected: 20
- Rows predicted: 20
- Rows compared: 20
- Error count: 91

### High-Value Field Accuracy

- claim_status: 0.750
- issue_type: 0.500
- object_part: 0.850
- evidence_standard_met: 0.900
- valid_image: 0.800
- severity: 0.500

### All Evaluated Field Accuracy

- evidence_standard_met: 0.900
- evidence_standard_met_reason: 0.000
- risk_flags: 0.450
- issue_type: 0.500
- object_part: 0.850
- claim_status: 0.750
- claim_status_justification: 0.000
- supporting_image_ids: 0.700
- valid_image: 0.800
- severity: 0.500

### Risk Flags

- Precision: 0.577
- Recall: 0.577
- F1: 0.577

### Supporting Image IDs

- Set precision: 0.842
- Set recall: 0.842
- Set F1: 0.842
- Average Jaccard overlap: 0.800

### Justification Quality

- Evidence reason non-empty rate: 1.000
- Claim justification non-empty rate: 1.000
- Claim justification mentions image ID rate: 1.000
- Average claim justification length: 297.4 chars

## Error Analysis

Top field errors:
- claim_status_justification: 20
- evidence_standard_met_reason: 20
- risk_flags: 11
- issue_type: 10
- severity: 10
- supporting_image_ids: 6
- claim_status: 5
- valid_image: 4
- object_part: 3
- evidence_standard_met: 2

Examples:
- Row 1 `evidence_standard_met_reason`: expected `The rear bumper is visible and the dent can be verified from the submitted image.`, predicted `Image img_1 shows the rear of the car from a direct rear angle; the rear bumper and adjacent body panels are clearly visible and the deformation/damage is assessable.`
- Row 1 `claim_status_justification`: expected `The image clearly shows a dent on the rear bumper and the user history does not add risk.`, predicted `img_1 clearly shows visible deformation and partial detachment of the rear bumper cover, with the lower bumper section hanging and crumpled on the right side; the trunk lid also shows deformation. The rear bumper damage claimed by the customer is visibly present.`
- Row 2 `evidence_standard_met_reason`: expected `The full front view provides context and the close-up image shows the scratch on the front bumper.`, predicted `Both images show the front of a white car with the front bumper clearly visible from angles suitable for assessing surface marks.`

## Operational Analysis

Sample set:
- Rows: 20
- Images: 29
- Fresh model calls: 20
- Cache hits: 0
- Fallback rows: 0
- Backup calls: 0
- Prompt tokens: 74694
- Completion tokens: 17424
- Cached/read tokens: 3572
- Cache write tokens: 0
- Runtime: 174.14s
- Average latency per token-baseline call: 25.47s

Backup reasons:
- none

Test set:
- Rows: 44
- Images: 82
- Expected model calls: 44
- Projected input tokens: 164327
- Projected output tokens: 38333
- Estimated full-test cost: $0.0953
- Estimated full-test summed provider latency: 1120.48s

Rate limits and operations:
- Configured max concurrency: 3
- Configured RPM limit: 60
- Approximate TPM requirement: 202660 tokens across the projected full test; divide by intended runtime minutes for required TPM.
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
