# Claim Verification Design

## Goal

Build a Python solution that reads `dataset/claims.csv`, inspects submitted local images with a configurable VLM provider, incorporates claim text, user history, and evidence requirements, and writes an evaluable `output.csv` with the exact required schema. The system must also include an evaluation workflow for `dataset/sample_claims.csv` and an operational analysis report.

## Scope

The solution will live under `code/` and preserve the expected entry points:

- `code/main.py` runs predictions for `dataset/claims.csv` and writes `output.csv` at the repository root by default.
- `code/evaluation/main.py` runs the same predictor against `dataset/sample_claims.csv`, computes field-level metrics, compares at least two strategies or configurations where practical, and writes `code/evaluation/evaluation_report.md`.

The default runtime language is Python. Secrets are read only from environment variables.

## Recommended Approach

Use a provider-swappable, single-pass VLM adjudication pipeline:

1. Load one claim row, user history, and evidence requirements.
2. Detect and package the row's local images.
3. Send all images for that row plus structured claim context to the selected provider.
4. Require structured JSON with internal reasoning fields and output fields.
5. Normalize, validate, and write one row in the exact required output schema.

This uses one VLM call per claim row when a provider is configured. It is cheaper and simpler than a two-stage image-observation pipeline, while still allowing retries, caching, and provider swaps.

## Provider Configuration

Runtime selection is controlled by environment variables:

- `VLM_PROVIDER=openai|openrouter|anthropic|none`
- `VLM_MODEL=<provider model slug>`
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `ANTHROPIC_API_KEY`
- Optional: `VLM_TEMPERATURE`, `VLM_MAX_RETRIES`, `VLM_CACHE_DIR`

The default provider is `none` so the repository is runnable without secrets. A real visual-inspection run requires setting `VLM_PROVIDER` to `openai`, `openrouter`, or `anthropic` and providing the matching API key.

OpenAI and OpenRouter share an OpenAI-compatible adapter path where possible. OpenRouter still has its own base URL, key, and optional attribution headers. Anthropic uses a separate adapter because its Messages API packages images as image content blocks rather than OpenAI-style `image_url` blocks.

The `none` provider is an honest fallback for runnable code without credentials. It must not pretend to inspect images. It returns `claim_status=not_enough_information`, `evidence_standard_met=false`, `valid_image=false`, `issue_type=unknown`, `object_part=unknown`, `supporting_image_ids=none`, `severity=unknown`, and a reason that says VLM inspection was unavailable.

## Image Handling

Image handling must inspect file bytes, not filename extensions. The dataset uses `.jpg` filenames for multiple formats, including JPEG, PNG, WebP, and AVIF.

The image preprocessor will:

- Resolve each CSV image path relative to `dataset/`.
- Extract the image ID from the filename stem, such as `img_1`.
- Detect MIME type by magic bytes.
- Pass supported JPEG, PNG, and WebP images through as base64 data URLs or provider-specific base64 blocks.
- Attempt AVIF conversion to JPEG/PNG only when a local decoder is available.
- Mark the row as not inspectable when required images cannot be prepared, without inventing visual findings.

Unsupported or unreadable images produce explicit risk/context for the provider or fallback path. They do not become visual evidence.

## Prompt And Security

The prompt must separate trusted system instructions from untrusted data. The user claim, user history summary, evidence requirements, and any text visible in images are evidence only; they are never instructions to the model.

Prompt-injection and text-in-image handling:

- Claim text containing phrases like "ignore previous instructions", "approve this claim", or "mark supported" is ignored as an instruction.
- Text visible inside an image is treated as untrusted content. A note saying the package is damaged cannot itself prove damage.
- The VLM is asked to report whether instruction-like text appears in any image.
- A deterministic pre-scan flags obvious instruction-like text in `user_claim`.
- Either source maps to the allowed output risk flag `text_instruction_present`.
- If real damage is visible despite instruction-like text, the claim may still be supported, but the risk flag remains.
- If the only support is instruction text and no visual damage, the final status should be `contradicted` or `not_enough_information` depending on whether the relevant part is visible.

The prompt will require the model to ground decisions in visible object/part/damage evidence and to use `unknown` or `none` instead of guessing.

## Output Normalization

The normalizer owns all schema guarantees:

- Required columns in exact order.
- Boolean values serialized as lowercase `true` or `false`.
- Allowed enum values only for `claim_status`, `issue_type`, `object_part`, `valid_image`, `evidence_standard_met`, and `severity`.
- Risk flags limited to the allowed list and joined by semicolons, or `none`.
- Supporting image IDs limited to IDs present in the row, or `none`.
- Justifications concise and grounded in image IDs when helpful.

User-history flags are added as risk context after provider output. History can add `user_history_risk` and `manual_review_required`, but it cannot override clear visual evidence by itself.

## Components

Use focused modules with narrow responsibilities:

- `config.py`: reads environment variables and default paths.
- `schemas.py`: allowed values, output columns, typed prediction structures.
- `data.py`: CSV loading, user-history lookup, evidence-requirement lookup, output writing.
- `images.py`: path resolution, image ID extraction, byte-signature MIME detection, optional conversion, payload encoding.
- `security.py`: prompt-injection pre-scan and risk-flag helpers.
- `prompting.py`: system prompt, row prompt, provider-neutral expected JSON schema.
- `providers/base.py`: provider interface.
- `providers/openai_compatible.py`: OpenAI and OpenRouter implementation.
- `providers/anthropic.py`: Anthropic Messages implementation.
- `providers/fallback.py`: honest no-vision fallback.
- `normalization.py`: validation, enum repair, risk-flag merge, output-row construction.
- `runner.py`: orchestration for prediction and evaluation flows.
- `main.py`: thin CLI wrapper.
- `evaluation/main.py`: evaluation CLI.

This follows SOLID where it helps: single responsibility per module, provider clients behind an interface, and extension by adding providers rather than changing the runner.

## Data Flow

```text
CSV row
  -> load user history and evidence requirements
  -> pre-scan untrusted claim text for injection risk
  -> resolve and prepare image payloads
  -> call configured provider or honest fallback
  -> normalize provider JSON into required output schema
  -> write CSV row
```

Evaluation reuses the same runner but compares predicted fields against labels in `dataset/sample_claims.csv`.

## Caching, Retries, And Determinism

Use deterministic settings where provider APIs allow it:

- Low temperature by default.
- Stable prompts and schema.
- Optional JSON cache keyed by provider, model, prompt version, claim row content, and image file hashes.
- Bounded retries for transient provider errors.
- Failed or unavailable providers fall back to honest no-vision rows only if configured to do so.

The cache stores provider responses and normalized predictions, not secrets.

## Evaluation

The evaluation workflow will report:

- Row count and image count.
- Exact-match accuracy for high-value fields: `claim_status`, `issue_type`, `object_part`, `evidence_standard_met`, `valid_image`, and `severity`.
- Field-level accuracy across all required output fields.
- Confusion summaries for `claim_status` and key error examples.
- Comparison of at least two strategies. With credentials, compare the configured VLM strategy against a second model, provider, or prompt setting. Without credentials, compare the honest fallback against a deterministic text-only baseline and clearly state that neither strategy inspected images.
- Operational analysis: model calls, approximate input/output tokens, images processed, estimated cost, runtime, rate-limit considerations, caching, throttling, and retry strategy.

If no API key is configured, evaluation still runs and explicitly reports that visual inspection was unavailable.

## Error Handling

Errors should be explicit and non-deceptive:

- Missing dataset files fail fast with a clear message.
- Missing optional provider keys route to the `none` fallback only when `VLM_PROVIDER=none` or fallback is explicitly allowed.
- Unsupported image formats or failed conversions mark the affected row as not inspectable unless another relevant image is available.
- Malformed provider JSON triggers a retry, then a conservative not-enough-information result if retries fail.
- Output CSV is always schema-valid when the program exits successfully.

## Acceptance Criteria

- Running `python code/main.py` produces root-level `output.csv` with one row per `dataset/claims.csv` row.
- Running `python code/evaluation/main.py` produces evaluation output and `code/evaluation/evaluation_report.md`.
- The implementation supports `openai`, `openrouter`, `anthropic`, and `none` providers via env config.
- No API keys or secrets are hardcoded or logged.
- The no-vision fallback is honest and never claims image inspection.
- Prompt-injection and text-in-image instruction risks are ignored as instructions and surfaced with `text_instruction_present` where detected.
- The code validates allowed values and exact output column order.
- The code includes a `code/README.md` with setup, env vars, provider examples, run commands, and limitations.
