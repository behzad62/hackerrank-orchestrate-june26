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
ALLOW_BACKUP_VLM=false
VLM_BACKUP_CHAIN=openrouter:openai/gpt-4.1-mini,anthropic:claude-3-5-sonnet-latest
OPENAI_API_KEY=sk-redacted
OPENROUTER_API_KEY=sk-or-redacted
ANTHROPIC_API_KEY=sk-ant-redacted
GEMINI_API_KEY=redacted
VLM_TEMPERATURE=0
VLM_MAX_RETRIES=2
VLM_RETRY_MAX_SLEEP_SECONDS=8
VLM_TIMEOUT_SECONDS=90
VLM_MAX_OUTPUT_TOKENS=1800
VLM_MAX_CONCURRENCY=1
VLM_REQUESTS_PER_MINUTE=0
VLM_BACKUP_MAX_CONCURRENCY=1
VLM_CACHE_DIR=.cache/vlm
PROMPT_CACHE_ENABLED=true
PROMPT_CACHE_RETENTION=24h
VLM_REASONING_ENABLED=false
VLM_REASONING_EFFORT=low
VLM_REASONING_MAX_TOKENS=0
VLM_REASONING_EXCLUDE=true
CLAIM_REVIEW_STRATEGY_MODE=one_pass
ADJUDICATOR_PROVIDER=
ADJUDICATOR_MODEL=
ALLOW_NO_VISION_FALLBACK=false
VLM_MODEL_PRICES=gemini:gemini-3.5-flash=1.50,9.00;openrouter:minimax/minimax-m3=0.30,1.20
EVAL_STRATEGIES=openrouter-minimax=openrouter:minimax/minimax-m3;two-pass-minimax=openrouter:minimax/minimax-m3,mode=two_pass,adjudicator=openrouter:minimax/minimax-m3
FINAL_STRATEGY=openrouter-minimax
EVAL_IGNORE_CACHE=false
CACHE_WRITE_ENABLED=true
```

`none` is an honest no-vision fallback for smoke testing. It does not inspect images and returns conservative `not_enough_information` rows.

`VLM_BACKUP_CHAIN` is only used when `ALLOW_BACKUP_VLM=true`. Backup VLMs are reliability fallbacks for provider/runtime failures such as exhausted quota, rate limits after retries, timeouts, server errors, truncated responses, malformed JSON, or temporary network errors. They are not used when the primary model returns a valid prediction such as `contradicted` or `not_enough_information`.

`VLM_REASONING_ENABLED` enables provider reasoning controls when the selected model supports them. `VLM_REASONING_EFFORT` accepts OpenRouter-style levels such as `minimal`, `low`, `medium`, `high`, `xhigh`, and `none`; native Gemini maps this to `thinkingLevel`. `VLM_REASONING_EXCLUDE=true` asks compatible providers not to return reasoning text in the response, which keeps JSON extraction cleaner.

If Gemini returns a provider `bad_request` while reasoning controls are enabled, set `VLM_REASONING_ENABLED=false`. Gemini structured JSON plus image review is sufficient for this task, and reasoning mode may create provider-specific payload issues.

`VLM_MODEL_PRICES` uses semicolon-separated `provider:model=input,output` entries, with prices in dollars per 1M tokens. Unlisted provider/model pairs are treated as `$0` in evaluation cost estimates until explicitly configured.

`CLAIM_REVIEW_STRATEGY_MODE` accepts `one_pass` or `two_pass`. In `two_pass`, the configured VLM first extracts visual facts from images, a deterministic rule layer builds a candidate decision, and `ADJUDICATOR_PROVIDER`/`ADJUDICATOR_MODEL` runs a text-only final adjudication using the same output contract and normalizer. Two-pass mode generally costs two model calls per fresh row.

`EVAL_STRATEGIES` compares multiple sample-evaluation strategies using semicolon-separated `name=provider:model` entries. Optional per-strategy overrides can be appended with commas, for example `openrouter-minimax=openrouter:minimax/minimax-m3,max_output_tokens=4096,reasoning_enabled=true`. Two-pass strategies use `mode=two_pass,adjudicator=provider:model`. `FINAL_STRATEGY` selects the strategy documented as the final `output.csv` strategy; if omitted, evaluation chooses the highest weighted sample score.

`EVAL_IGNORE_CACHE=true` forces fresh provider calls during evaluation so token and latency telemetry can be refreshed. Successful provider responses are still written to cache unless `CACHE_WRITE_ENABLED=false` or `--no-cache-write` is used.

`VLM_MAX_CONCURRENCY` enables bounded per-claim parallelism. The default is `1` for sequential behavior. `VLM_REQUESTS_PER_MINUTE` adds a simple shared request-start limiter when greater than zero, and `VLM_BACKUP_MAX_CONCURRENCY` prevents backup-provider stampedes when the primary provider is broadly failing.

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

Fresh two-strategy evaluation:

```bash
python code/evaluation/main.py --env .env --ignore-cache --strategy openrouter-minimax=openrouter:minimax/minimax-m3 --strategy none-fallback=none:none --final-strategy openrouter-minimax --no-fallback
```

Fresh Minimax vs Gemini evaluation:

```bash
python code/evaluation/main.py --env .env --ignore-cache --strategy openrouter-minimax=openrouter:minimax/minimax-m3 --strategy gemini-flash=gemini:gemini-3.5-flash --final-strategy openrouter-minimax --no-fallback
```

Cached repeat evaluation:

```bash
python code/evaluation/main.py --env .env --strategy openrouter-minimax=openrouter:minimax/minimax-m3 --strategy none-fallback=none:none --final-strategy openrouter-minimax --no-fallback
```

Outputs:

- `code/evaluation/evaluation_report.md`
- `code/evaluation/sample_predictions.csv`
- `code/evaluation/errors.csv`
- `code/evaluation/metrics.json`
- `code/evaluation/runs/<strategy>/sample_predictions.csv`
- `code/evaluation/runs/<strategy>/metrics.json`
- `code/evaluation/runs/<strategy>/errors.csv`
- `code/evaluation/runs/<strategy>/run.jsonl`

The report includes a strategy comparison table, the final strategy to use for `output.csv`, selected-strategy sample metrics, error analysis, operational analysis, caching notes, and known limitations.

## Logs And Cache

Logs are written under `logs/` as JSONL and never include API keys, raw image bytes, or base64 payloads.

Cache files are written under `.cache/vlm/` by default and are keyed by provider, model, prompt version, row content, user history, evidence requirements, image hashes, and normalizer version. Generation settings that can change predictions, including max output tokens and reasoning controls, are included in the effective cache key.

Provider prompt caching is enabled by default when supported. The prompt is ordered with stable instructions, allowed values, output schema, evidence requirements, injection policy, and examples first; per-claim user history, claim text, image IDs, image payloads, and image metadata follow after that. Provider response logs include cache telemetry when returned by the API, including cached tokens, cache hit ratio, retention, and Anthropic cache creation/read tokens.

When backup VLMs are enabled, logs include the primary provider, final provider, whether a backup was used, and the backup reason for each completed claim. Backup responses are not cached under the primary provider's cache key.

## Security Behavior

The dataset fields are untrusted. The system ignores instructions found in `user_claim`, image text, labels, filenames, and user history. Instruction-like content is surfaced as `text_instruction_present`.

## User History

`dataset/user_history.csv` is read-only. Current `claims.csv` rows are processed independently and never update history.

## Limitations

- Visual quality depends on the configured VLM.
- AVIF images require local decoding through `pillow-avif-plugin`.
- The fallback provider is only for runnable smoke tests and degraded emergency output.
