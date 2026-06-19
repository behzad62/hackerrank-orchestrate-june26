# Claim Verification Solution

Python solution for the HackerRank Orchestrate multi-modal evidence review challenge.

## Setup

```bash
python -m pip install -r code/requirements.txt
```

PowerShell:

```powershell
python -m pip install -r code/requirements.txt
```

## Environment

```bash
VLM_PROVIDER=openai|openrouter|anthropic|gemini|none
VLM_MODEL=gpt-4.1-mini
OPENAI_API_KEY=sk-redacted
OPENROUTER_API_KEY=sk-or-redacted
ANTHROPIC_API_KEY=sk-ant-redacted
GEMINI_API_KEY=redacted
VLM_TEMPERATURE=0
VLM_MAX_RETRIES=2
VLM_RETRY_MAX_SLEEP_SECONDS=8
VLM_TIMEOUT_SECONDS=90
VLM_MAX_OUTPUT_TOKENS=1800
VLM_CACHE_DIR=.cache/vlm
PROMPT_CACHE_ENABLED=true
PROMPT_CACHE_RETENTION=24h
GEMINI_THINKING_LEVEL=medium
ALLOW_NO_VISION_FALLBACK=false
VLM_INPUT_PRICE_PER_MILLION=0
VLM_OUTPUT_PRICE_PER_MILLION=0
```

`none` is an honest no-vision fallback for smoke testing. It does not inspect images and returns conservative `not_enough_information` rows.

## Run Final Predictions

```bash
python code/main.py --claims dataset/claims.csv --output output.csv --provider openai --model gpt-4.1-mini
```

PowerShell:

```powershell
$env:VLM_PROVIDER='openai'
$env:VLM_MODEL='gpt-4.1-mini'
$env:ALLOW_NO_VISION_FALLBACK='false'
python code/main.py
```

## Run Evaluation

```bash
python code/evaluation/main.py
```

Outputs:

- `code/evaluation/evaluation_report.md`
- `code/evaluation/sample_predictions.csv`
- `code/evaluation/errors.csv`
- `code/evaluation/metrics.json`

## Logs And Cache

Logs are written under `logs/` as JSONL and never include API keys, raw image bytes, or base64 payloads.

Cache files are written under `.cache/vlm/` by default and are keyed by provider, model, prompt version, row content, user history, evidence requirements, image hashes, and normalizer version. Generation settings that can change predictions, including max output tokens and Gemini thinking level, are included in the effective cache key.

Provider prompt caching is enabled by default when supported. The prompt is ordered with stable instructions, allowed values, output schema, evidence requirements, injection policy, and examples first; per-claim user history, claim text, image IDs, image payloads, and image metadata follow after that. Provider response logs include cache telemetry when returned by the API, including cached tokens, cache hit ratio, retention, and Anthropic cache creation/read tokens.

## Security Behavior

The dataset fields are untrusted. The system ignores instructions found in `user_claim`, image text, labels, filenames, and user history. Instruction-like content is surfaced as `text_instruction_present`.

## User History

`dataset/user_history.csv` is read-only. Current `claims.csv` rows are processed independently and never update history.

## Limitations

- Visual quality depends on the configured VLM.
- AVIF images require local decoding through `pillow-avif-plugin`.
- The fallback provider is only for runnable smoke tests and degraded emergency output.
