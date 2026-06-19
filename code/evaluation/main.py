from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from config import AppConfig, build_common_arg_parser, load_env_file, parse_model_prices
from data import load_claim_rows, load_evidence_requirements, load_user_history
from evaluation.metrics import (
    compare_rows,
    core_decision_error_analysis,
    write_errors_csv,
    write_metrics_json,
)
from evaluation.strategies import EvalStrategy, default_strategies, parse_strategies
from images import prepare_images
from prompting import build_text_prompt
from runner import _selected_requirements, run_predictions
from schemas import AppPaths, OUTPUT_COLUMNS, PredictionContext
from security import detect_prompt_injection_flags


HIGH_VALUE_FIELDS = [
    "claim_status",
    "issue_type",
    "object_part",
    "evidence_standard_met",
    "valid_image",
    "severity",
]


@dataclass(frozen=True)
class TokenEstimate:
    source: str
    sample_prompt_tokens: int
    sample_completion_tokens: int
    sample_cached_tokens: int
    sample_cache_write_tokens: int
    sample_latency_ms: int
    calls_by_model: dict[tuple[str, str], dict[str, int]]


@dataclass(frozen=True)
class StrategyResult:
    strategy: EvalStrategy
    run_dir: Path
    predictions_path: Path
    errors_path: Path
    metrics_path: Path
    log_path: Path
    metrics: dict
    errors: list[dict[str, str]]
    run_summary: dict[str, object]
    token_estimate: TokenEstimate
    estimated_full_test_cost: float
    projected_prompt_tokens: int
    projected_completion_tokens: int
    estimated_runtime_seconds: float
    price_warning: str = ""


def _count_images(rows: list[dict[str, str]]) -> int:
    return sum(
        len([part for part in row.get("image_paths", "").split(";") if part.strip()])
        for row in rows
    )


def _write_predictions_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})


def _format_field_accuracy(metrics: dict, fields: list[str]) -> str:
    accuracy = metrics.get("field_accuracy", {})
    return "\n".join(
        f"- {field}: {float(accuracy.get(field, 0.0)):.3f}" for field in fields
    )


def _write_report(
    path: Path,
    metrics: dict,
    sample_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    provider: str,
    model: str,
    observed_provider: str,
    fallback_allowed: bool,
    fallback_used: bool,
    sample_model_calls: int,
    test_model_calls: int,
    sample_prompt_tokens: int = 0,
    sample_completion_tokens: int = 0,
    sample_cached_tokens: int = 0,
    sample_cache_write_tokens: int = 0,
    sample_latency_ms: int = 0,
    input_price_per_million: float = 0.0,
    output_price_per_million: float = 0.0,
    model_prices: dict[tuple[str, str], tuple[float, float]] | None = None,
    calls_by_model: dict[tuple[str, str], dict[str, int]] | None = None,
    backup_reasons: dict[str, int] | None = None,
    primary_provider_calls: int = 0,
    backup_provider_calls: int = 0,
    fallback_rows: int = 0,
    max_concurrency: int = 1,
    rate_limit_waits: int = 0,
    run_total_duration_ms: int = 0,
    cache_hits: int = 0,
) -> None:
    sample_images = _count_images(sample_rows)
    test_images = _count_images(test_rows)
    scores = metrics.get("risk_flag_scores", {})
    image_scores = metrics.get("supporting_image_id_scores", {})
    model_prices = model_prices or {}
    calls_by_model = calls_by_model or {}
    backup_reasons = backup_reasons or {}
    priced_response_calls = sum(int(usage.get("calls", 0)) for usage in calls_by_model.values())
    token_average_denominator = priced_response_calls or sample_model_calls
    avg_prompt_tokens = sample_prompt_tokens / token_average_denominator if token_average_denominator else 0.0
    avg_completion_tokens = sample_completion_tokens / token_average_denominator if token_average_denominator else 0.0
    cache_hit_ratio = sample_cached_tokens / sample_prompt_tokens if sample_prompt_tokens else 0.0
    row_scale = (len(test_rows) / len(sample_rows)) if sample_rows else 0.0
    if calls_by_model:
        projected_prompt_tokens = int(
            round(sum(int(usage.get("prompt_tokens", 0)) for usage in calls_by_model.values()) * row_scale)
        )
        projected_completion_tokens = int(
            round(sum(int(usage.get("completion_tokens", 0)) for usage in calls_by_model.values()) * row_scale)
        )
    else:
        projected_prompt_tokens = int(round(avg_prompt_tokens * test_model_calls))
        projected_completion_tokens = int(round(avg_completion_tokens * test_model_calls))
    estimated_cost = _estimate_projected_cost(
        calls_by_model,
        model_prices,
        default_input=input_price_per_million,
        default_output=output_price_per_million,
        row_scale=row_scale,
        fallback_prompt_tokens=projected_prompt_tokens,
        fallback_completion_tokens=projected_completion_tokens,
    )
    avg_latency_seconds = (sample_latency_ms / token_average_denominator / 1000) if token_average_denominator else 0.0
    estimated_runtime_seconds = avg_latency_seconds * test_model_calls
    estimates_available = bool(sample_model_calls or not test_model_calls)
    no_fresh_call_text = "unavailable (sample run had no fresh provider calls)"
    projected_prompt_tokens_text = str(projected_prompt_tokens) if estimates_available else no_fresh_call_text
    projected_completion_tokens_text = str(projected_completion_tokens) if estimates_available else no_fresh_call_text
    estimated_cost_text = (
        f"${estimated_cost:.4f}"
        if estimates_available
        else "unavailable (sample run had no fresh token baseline)"
    )
    observed_latency_text = f"{sample_latency_ms / 1000:.2f}s" if estimates_available else no_fresh_call_text
    avg_latency_text = f"{avg_latency_seconds:.2f}s" if estimates_available else no_fresh_call_text
    estimated_runtime_text = (
        f"{estimated_runtime_seconds:.2f}s"
        if estimates_available
        else "unavailable (sample run had no fresh latency baseline)"
    )
    concurrency_text = (
        "Calls use bounded parallel execution with up to "
        f"{max_concurrency} in-flight provider requests."
        if max_concurrency > 1
        else "Calls run sequentially with one in-flight provider request."
    )
    rpm_text = (
        "RPM consideration: local parallelism can increase burst pressure; "
        "the configured RPM limiter, retry backoff, and provider latency bound request rate."
        if max_concurrency > 1
        else "RPM consideration: sequential execution targets at most one in-flight provider request, so effective RPM is bounded by provider latency and retry backoff rather than local parallelism."
    )
    if estimates_available:
        tpm_consideration = (
            "projected full-test token volume is approximately "
            f"{projected_prompt_tokens + projected_completion_tokens} total tokens; "
            "configure provider TPM limits above this divided by the intended runtime window."
        )
    else:
        tpm_consideration = (
            "projected token volume is unavailable because the sample run had no fresh provider calls; "
            "run one uncached sample pass or use provider pricing/token metadata before final cost planning."
        )
    if provider == "none":
        fallback_note = "No VLM provider was configured, so images were not inspected and model cost is $0."
    elif fallback_used:
        fallback_note = (
            "A VLM provider was configured, but no-vision fallback was observed for at least one row. "
            "Successful provider rows may have inspected images; fallback rows did not."
        )
    elif sample_model_calls == 0:
        fallback_note = (
            "No fresh provider calls were made in this run. Results came from cached provider output, "
            "so any visual inspection occurred in the earlier run that populated the cache."
        )
    else:
        fallback_note = "A configured VLM provider was used for image inspection."

    model_price_lines = _format_model_price_lines(calls_by_model, model_prices, input_price_per_million, output_price_per_million)
    backup_reason_lines = _format_backup_reason_lines(backup_reasons)

    report = f"""# Evaluation Report

## Strategy

- Provider configured: `{provider}`
- Provider observed in sample run: `{observed_provider}`
- Model: `{model or 'none'}`
- Fallback allowed: `{fallback_allowed}`
- Fallback actually used/no-vision: `{fallback_used}`
- Fallback honesty: {fallback_note}

## Metrics

- Rows expected: {metrics.get('rows_expected', 0)}
- Rows predicted: {metrics.get('rows_predicted', 0)}
- Rows compared: {metrics.get('rows_compared', 0)}
- Error count: {metrics.get('error_count', 0)}

### High-Value Field Accuracy

{_format_field_accuracy(metrics, HIGH_VALUE_FIELDS)}

### All Evaluated Field Accuracy

{_format_field_accuracy(metrics, list(metrics.get('field_accuracy', {}).keys()))}

### Risk Flags

- Precision: {float(scores.get('precision', 0.0)):.3f}
- Recall: {float(scores.get('recall', 0.0)):.3f}
- F1: {float(scores.get('f1', 0.0)):.3f}

### Supporting Image IDs

- Set precision: {float(image_scores.get('precision', 0.0)):.3f}
- Set recall: {float(image_scores.get('recall', 0.0)):.3f}
- Set F1: {float(image_scores.get('f1', 0.0)):.3f}
- Average Jaccard overlap: {float(image_scores.get('average_jaccard', 0.0)):.3f}

## Operational Analysis

Sample set:
- Rows: {len(sample_rows)}
- Images: {sample_images}
- Model calls: {sample_model_calls}
- Primary provider calls: {primary_provider_calls}
- Backup provider calls: {backup_provider_calls}
- Fallback rows: {fallback_rows}
- Cache hits: {cache_hits}
- Configured max concurrency: {max_concurrency}
- Rate-limit waits: {rate_limit_waits}

Backup reasons:
{backup_reason_lines}

Test set:
- Rows: {len(test_rows)}
- Images: {test_images}
- Expected model calls: {test_model_calls}

The system uses one multimodal call per claim row when a real VLM provider is configured. Images for the same claim are submitted together so the model can compare overview and close-up evidence.

Pricing assumptions:
- Provider pricing varies by selected model.
- Use provider token accounting from logs/provider metadata when available.
- Unlisted model input price default: ${input_price_per_million:.4f} / 1M tokens.
- Unlisted model output price default: ${output_price_per_million:.4f} / 1M tokens.
- Model-specific price assumptions:
{model_price_lines}
- With `VLM_PROVIDER=none`, images were not inspected and model cost is $0.
- If fallback is observed during a real-provider run, fallback rows did not receive visual inspection; provider rows may still have token costs.

Observed token usage:
- Observed prompt tokens: {sample_prompt_tokens}
- Observed output tokens: {sample_completion_tokens}
- Observed prompt cache write tokens: {sample_cache_write_tokens}
- Observed prompt cache read tokens: {sample_cached_tokens}
- Observed prompt cache hit ratio: {cache_hit_ratio:.3f}
- Observed average prompt tokens per fresh call: {avg_prompt_tokens:.1f}
- Observed average output tokens per fresh call: {avg_completion_tokens:.1f}

Estimated full-test token usage and cost:
- Projected input tokens: {projected_prompt_tokens_text}
- Projected output tokens: {projected_completion_tokens_text}
- Estimated full-test cost: {estimated_cost_text}

Latency/runtime estimate:
- Observed total provider latency: {observed_latency_text}
- Observed total run runtime: {run_total_duration_ms / 1000:.2f}s
- Observed average latency per fresh call: {avg_latency_text}
- Estimated full-test summed provider latency at current settings: {estimated_runtime_text}

Runtime and rate limits:
- {concurrency_text}
- {rpm_text}
- TPM consideration: {tpm_consideration}
- Retry policy uses bounded retries for rate limits, server errors, timeouts, truncated responses, and JSON parse errors.
- Cache keys include provider, model, prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Caching and batching:
- Successful provider responses are cached by stable content hash.
- Fallback results after provider errors are not cached as successful model evidence.
- Rows are not batched across claims; image sets are grouped per claim.

Known limitations:
- No-vision fallback is intentionally conservative and should not be used for final predictions unless explicitly allowed.
- Fallback output does not inspect image content and therefore reports `not_enough_information`.
- AVIF images require a local decoder through `pillow-avif-plugin`; unsupported conversion marks the image unreadable.
- Text found in images is treated as untrusted and can add `text_instruction_present`.

Failure modes observed in logs:
- Review `logs/run.jsonl` for provider error categories, retry counts, cache hits, and normalization repairs.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def _price_for_model(
    provider: str,
    model: str,
    model_prices: dict[tuple[str, str], tuple[float, float]],
    default_input: float,
    default_output: float,
) -> tuple[float, float]:
    return model_prices.get((provider.strip().lower(), model.strip()), (default_input, default_output))


def _estimate_projected_cost(
    calls_by_model: dict[tuple[str, str], dict[str, int]],
    model_prices: dict[tuple[str, str], tuple[float, float]],
    *,
    default_input: float,
    default_output: float,
    row_scale: float,
    fallback_prompt_tokens: int,
    fallback_completion_tokens: int,
) -> float:
    if not calls_by_model:
        return ((fallback_prompt_tokens * default_input) + (fallback_completion_tokens * default_output)) / 1_000_000
    total = 0.0
    for (provider, model), usage in calls_by_model.items():
        input_price, output_price = _price_for_model(provider, model, model_prices, default_input, default_output)
        projected_prompt = int(round(int(usage.get("prompt_tokens", 0)) * row_scale))
        projected_completion = int(round(int(usage.get("completion_tokens", 0)) * row_scale))
        total += (projected_prompt * input_price) + (projected_completion * output_price)
    return total / 1_000_000


def _format_model_price_lines(
    calls_by_model: dict[tuple[str, str], dict[str, int]],
    model_prices: dict[tuple[str, str], tuple[float, float]],
    default_input: float,
    default_output: float,
) -> str:
    if not calls_by_model:
        return "- none observed in this run"
    lines = []
    for provider, model in sorted(calls_by_model):
        usage = calls_by_model[(provider, model)]
        input_price, output_price = _price_for_model(provider, model, model_prices, default_input, default_output)
        lines.append(
            f"- {provider}/{model}: {int(usage.get('calls', 0))} calls, "
            f"input ${input_price:.4f} / 1M, output ${output_price:.4f} / 1M"
        )
    return "\n".join(lines)


def _format_backup_reason_lines(backup_reasons: dict[str, int]) -> str:
    if not backup_reasons:
        return "- none"
    return "\n".join(f"- {reason}: {count}" for reason, count in sorted(backup_reasons.items()))


def _format_strategy_table(results: list[StrategyResult]) -> str:
    header = (
        "| Strategy | Mode | Vision Provider | Vision Model | Adjudicator | Fresh calls | Cache hits | Fallback rows | "
        "claim_status | issue_type | object_part | severity | Risk F1 | Image ID F1 | Est. full-test cost |"
    )
    separator = "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    rows = [header, separator]
    for result in results:
        accuracy = result.metrics.get("field_accuracy", {})
        risk_scores = result.metrics.get("risk_flag_scores", {})
        image_scores = result.metrics.get("supporting_image_id_scores", {})
        summary = result.run_summary
        adjudicator = (
            f"{result.strategy.adjudicator_provider}/{result.strategy.adjudicator_model}"
            if result.strategy.mode == "two_pass"
            else "same"
        )
        rows.append(
            "| "
            + " | ".join(
                [
                    result.strategy.name,
                    result.strategy.mode,
                    result.strategy.provider,
                    result.strategy.model or "none",
                    adjudicator,
                    str(int(summary.get("model_calls") or 0)),
                    str(int(summary.get("cache_hits") or 0)),
                    str(int(summary.get("fallback_rows") or 0)),
                    f"{float(accuracy.get('claim_status', 0.0)):.3f}",
                    f"{float(accuracy.get('issue_type', 0.0)):.3f}",
                    f"{float(accuracy.get('object_part', 0.0)):.3f}",
                    f"{float(accuracy.get('severity', 0.0)):.3f}",
                    f"{float(risk_scores.get('f1', 0.0)):.3f}",
                    f"{float(image_scores.get('f1', 0.0)):.3f}",
                    f"${result.estimated_full_test_cost:.4f}",
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def _format_error_analysis(errors: list[dict[str, str]]) -> str:
    if not errors:
        return "- No field mismatches found."
    counts: dict[str, int] = {}
    for error in errors:
        field = error.get("field", "unknown")
        counts[field] = counts.get(field, 0) + 1
    count_lines = "\n".join(
        f"- {field}: {count}" for field, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    )
    examples = []
    for error in errors[:3]:
        examples.append(
            f"- Row {error.get('row_index', '?')} `{error.get('field', '')}`: "
            f"expected `{error.get('expected', '')}`, predicted `{error.get('predicted', '')}`"
        )
    return f"Top field errors:\n{count_lines}\n\nExamples:\n" + "\n".join(examples)


def _format_pair_counts(title: str, pairs: dict[tuple[str, str], int]) -> str:
    if not pairs:
        return f"{title}:\n- none"
    lines = [
        f"- expected `{expected}`, predicted `{predicted}`: {count}"
        for (expected, predicted), count in sorted(pairs.items(), key=lambda item: (-item[1], item[0]))
    ]
    return f"{title}:\n" + "\n".join(lines)


def _format_flag_counts(title: str, counts: dict[str, int]) -> str:
    if not counts:
        return f"{title}:\n- none"
    return f"{title}:\n" + "\n".join(
        f"- {flag}: {count}" for flag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _format_core_decision_error_analysis(errors: list[dict[str, str]]) -> str:
    analysis = core_decision_error_analysis(errors)
    field_counts = analysis.get("field_counts", {})
    if field_counts:
        field_lines = "\n".join(
            f"- {field}: {count}" for field, count in sorted(field_counts.items(), key=lambda item: (-item[1], item[0]))
        )
    else:
        field_lines = "- none"
    return "\n\n".join(
        [
            f"Core decision error count: {analysis.get('core_error_count', 0)}",
            "Core field errors:\n" + field_lines,
            _format_pair_counts("Claim status mistakes", analysis.get("claim_status_pairs", {})),
            _format_pair_counts("Issue type mistakes", analysis.get("issue_type_pairs", {})),
            _format_pair_counts("Severity mistakes", analysis.get("severity_pairs", {})),
            _format_flag_counts("Risk flag false positives", analysis.get("risk_flag_false_positives", {})),
            _format_flag_counts("Risk flag false negatives", analysis.get("risk_flag_false_negatives", {})),
        ]
    )


def _format_justification_quality(metrics: dict) -> str:
    quality = metrics.get("justification_quality", {})
    return "\n".join(
        [
            f"- Evidence reason non-empty rate: {float(quality.get('evidence_standard_met_reason_non_empty_rate', 0.0)):.3f}",
            f"- Claim justification non-empty rate: {float(quality.get('claim_status_justification_non_empty_rate', 0.0)):.3f}",
            f"- Claim justification mentions image ID rate: {float(quality.get('claim_status_justification_mentions_image_id_rate', 0.0)):.3f}",
            f"- Average claim justification length: {float(quality.get('average_justification_length', 0.0)):.1f} chars",
        ]
    )


def _format_backup_chain(cfg: AppConfig) -> str:
    if not cfg.backup_chain:
        return "none"
    return ",".join(f"{spec.provider}:{spec.model}" for spec in cfg.backup_chain)


def _write_multi_strategy_report(
    path: Path,
    strategy_results: list[StrategyResult],
    final_result: StrategyResult,
    final_reason: str,
    sample_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    cfg: AppConfig,
) -> None:
    final_metrics = final_result.metrics
    final_scores = final_metrics.get("risk_flag_scores", {})
    final_image_scores = final_metrics.get("supporting_image_id_scores", {})
    final_summary = final_result.run_summary
    token_estimate = final_result.token_estimate
    token_call_count = sum(int(usage.get("calls", 0)) for usage in token_estimate.calls_by_model.values())
    avg_latency_seconds = (
        token_estimate.sample_latency_ms / token_call_count / 1000
        if token_call_count
        else 0.0
    )
    real_vlm_count = sum(1 for result in strategy_results if result.strategy.provider != "none")
    comparison_warning = (
        ""
        if real_vlm_count >= 2
        else "\n\nWarning: fewer than two real VLM strategies were configured; include another provider/model strategy for a stronger comparison."
    )
    price_warnings = [result.price_warning for result in strategy_results if result.price_warning]
    price_warning_text = "\n".join(f"- {warning}" for warning in price_warnings) if price_warnings else "- none"
    backup_reason_lines = _format_backup_reason_lines(dict(final_summary.get("backup_reasons") or {}))
    model_price_lines = _format_model_price_lines(
        token_estimate.calls_by_model,
        parse_model_prices(os.environ.get("VLM_MODEL_PRICES", "")),
        0.0,
        0.0,
    )
    tpm_total = final_result.projected_prompt_tokens + final_result.projected_completion_tokens
    final_command = (
        "python code/main.py --env .env "
        f"--provider {final_result.strategy.provider} --model {final_result.strategy.model or 'none'} "
        f"--strategy-mode {final_result.strategy.mode} "
        + (
            f"--adjudicator-provider {final_result.strategy.adjudicator_provider} "
            f"--adjudicator-model {final_result.strategy.adjudicator_model} "
            if final_result.strategy.mode == "two_pass"
            else ""
        )
        + ("--no-fallback" if not cfg.allow_no_vision_fallback else "--fallback")
    )
    report = f"""# Evaluation Report

## Strategies Compared

{_format_strategy_table(strategy_results)}
{comparison_warning}

## Final Strategy Used For output.csv

- Strategy name: {final_result.strategy.name}
- Strategy mode: {final_result.strategy.mode}
- Vision provider: {final_result.strategy.provider}
- Vision model: {final_result.strategy.model or 'none'}
- Adjudicator: {final_result.strategy.adjudicator_provider + '/' + final_result.strategy.adjudicator_model if final_result.strategy.mode == 'two_pass' else 'same as vision model'}
- Backup chain: {_format_backup_chain(cfg)}
- Fallback allowed for final: {str(cfg.allow_no_vision_fallback).lower()}
- Max concurrency: {cfg.max_concurrency}
- RPM limit: {cfg.requests_per_minute}
- Prompt cache: {'enabled' if cfg.prompt_cache_enabled else 'disabled'}
- Reason selected: {final_reason}
- Final output command: `{final_command}`

## Final Strategy Sample Metrics

- Rows expected: {final_metrics.get('rows_expected', 0)}
- Rows predicted: {final_metrics.get('rows_predicted', 0)}
- Rows compared: {final_metrics.get('rows_compared', 0)}
- Error count: {final_metrics.get('error_count', 0)}

### High-Value Field Accuracy

{_format_field_accuracy(final_metrics, HIGH_VALUE_FIELDS)}

### All Evaluated Field Accuracy

{_format_field_accuracy(final_metrics, list(final_metrics.get('field_accuracy', {}).keys()))}

### Risk Flags

- Precision: {float(final_scores.get('precision', 0.0)):.3f}
- Recall: {float(final_scores.get('recall', 0.0)):.3f}
- F1: {float(final_scores.get('f1', 0.0)):.3f}

### Supporting Image IDs

- Set precision: {float(final_image_scores.get('precision', 0.0)):.3f}
- Set recall: {float(final_image_scores.get('recall', 0.0)):.3f}
- Set F1: {float(final_image_scores.get('f1', 0.0)):.3f}
- Average Jaccard overlap: {float(final_image_scores.get('average_jaccard', 0.0)):.3f}

### Justification Quality

{_format_justification_quality(final_metrics)}

## Core Decision Error Analysis

{_format_core_decision_error_analysis(final_result.errors)}

## Error Analysis

{_format_error_analysis(final_result.errors)}

## Operational Analysis

Sample set:
- Rows: {len(sample_rows)}
- Images: {_count_images(sample_rows)}
- Fresh model calls: {int(final_summary.get('model_calls') or 0)}
- Cache hits: {int(final_summary.get('cache_hits') or 0)}
- Fallback rows: {int(final_summary.get('fallback_rows') or 0)}
- Backup calls: {int(final_summary.get('backup_provider_calls') or 0)}
- Prompt tokens: {token_estimate.sample_prompt_tokens}
- Completion tokens: {token_estimate.sample_completion_tokens}
- Cached/read tokens: {token_estimate.sample_cached_tokens}
- Cache write tokens: {token_estimate.sample_cache_write_tokens}
- Runtime: {int(final_summary.get('run_total_duration_ms') or 0) / 1000:.2f}s
- Average latency per token-baseline call: {avg_latency_seconds:.2f}s

Backup reasons:
{backup_reason_lines}

Test set:
- Rows: {len(test_rows)}
- Images: {_count_images(test_rows)}
- Expected model calls: {int(final_summary.get('test_model_calls') or 0)}
- Projected input tokens: {final_result.projected_prompt_tokens}
- Projected output tokens: {final_result.projected_completion_tokens}
- Estimated full-test cost: ${final_result.estimated_full_test_cost:.4f}
- Estimated full-test summed provider latency: {final_result.estimated_runtime_seconds:.2f}s

Rate limits and operations:
- Configured max concurrency: {cfg.max_concurrency}
- Configured RPM limit: {cfg.requests_per_minute}
- Approximate TPM requirement: {tpm_total} tokens across the projected full test; divide by intended runtime minutes for required TPM.
- Retry strategy: bounded retries for rate limits, server errors, timeouts, truncated responses, malformed JSON, and temporary network errors.
- Backup strategy: backup VLM chain is used only for provider/runtime failures, not for valid model judgments.
- Caching strategy: response cache keys include provider, model, effective prompt version, row content, user history, evidence requirements, image hashes, and normalizer version.

Pricing assumptions:
- Prices are read from `VLM_MODEL_PRICES` as `provider:model=input,output` in dollars per 1M tokens.
- Missing provider/model prices are treated as $0 and explicitly warned about below.
- Model-specific prices:
{model_price_lines}
- Price warnings:
{price_warning_text}

## Caching Notes

- Token source: {token_estimate.source}
- Prompt cache enabled: {str(cfg.prompt_cache_enabled).lower()}
- Response cache ignore mode: {str(cfg.ignore_cache).lower()}
- Response cache write enabled: {str(cfg.cache_write_enabled).lower()}
- If token source is approximate prompt-size estimate, input tokens are estimated from prompt characters and output tokens use the configured max-output budget as a conservative bound.
- Image token usage: provider-specific or unavailable unless provider metadata includes it in prompt token accounting.

## Known Limitations

- No-vision fallback is intentionally conservative and should not be used for final predictions unless explicitly allowed.
- Fallback output does not inspect image content and reports `not_enough_information`.
- AVIF images require a local decoder through `pillow-avif-plugin`; unsupported conversion marks the image unreadable.
- Text found in images is treated as untrusted and can add `text_instruction_present`.
- Free-text justification exact-match scores are kept in all-field metrics, but justification quality is reported separately because exact text does not need to match sample wording.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def _sample_predictions_path(output_arg: Path | None, default_evaluation_dir: Path) -> Path:
    if output_arg is None:
        return default_evaluation_dir / "sample_predictions.csv"
    if output_arg.exists() and output_arg.is_dir():
        return output_arg / "sample_predictions.csv"
    if output_arg.suffix:
        return output_arg
    return output_arg / "sample_predictions.csv"


def _strategy_score(metrics: dict) -> float:
    accuracy = metrics.get("field_accuracy", {})
    risk_scores = metrics.get("risk_flag_scores", {})
    image_scores = metrics.get("supporting_image_id_scores", {})
    return (
        0.30 * float(accuracy.get("claim_status", 0.0))
        + 0.25 * float(accuracy.get("issue_type", 0.0))
        + 0.15 * float(accuracy.get("severity", 0.0))
        + 0.15 * float(risk_scores.get("f1", 0.0))
        + 0.10 * float(accuracy.get("object_part", 0.0))
        + 0.05 * float(image_scores.get("f1", 0.0))
    )


def _apply_strategy(cfg: AppConfig, strategy: EvalStrategy, run_dir: Path) -> AppConfig:
    if cfg.paths is None:
        raise ValueError("AppConfig.paths is required")
    strategy_paths = replace(
        cfg.paths,
        logs_dir=run_dir,
        output_csv=run_dir / "sample_predictions.csv",
    )
    return replace(
        cfg,
        provider=strategy.provider,
        model=strategy.model,
        strategy_mode=strategy.mode,
        adjudicator_provider=strategy.adjudicator_provider or cfg.adjudicator_provider,
        adjudicator_model=strategy.adjudicator_model or cfg.adjudicator_model,
        prompt_version=strategy.prompt_version or cfg.prompt_version,
        reasoning_enabled=(
            strategy.reasoning_enabled if strategy.reasoning_enabled is not None else cfg.reasoning_enabled
        ),
        reasoning_effort=strategy.reasoning_effort or cfg.reasoning_effort,
        max_output_tokens=strategy.max_output_tokens or cfg.max_output_tokens,
        prompt_cache_enabled=(
            strategy.prompt_cache_enabled
            if strategy.prompt_cache_enabled is not None
            else cfg.prompt_cache_enabled
        ),
        paths=strategy_paths,
    )


def _estimate_prompt_size_tokens(rows: list[dict[str, str]], paths: AppPaths) -> int:
    user_history = load_user_history(paths.user_history_csv)
    all_requirements = load_evidence_requirements(paths.evidence_requirements_csv)
    total_chars = 0
    for row_index, row in enumerate(rows, start=1):
        prepared_images = prepare_images(paths.repo_root, row.get("image_paths", ""), paths.images_dir)
        history = user_history.get(row.get("user_id", ""), {})
        requirements = _selected_requirements(all_requirements, row.get("claim_object", ""))
        context = PredictionContext(
            row_index=row_index,
            row=row,
            user_history=history,
            evidence_requirements=requirements,
            all_evidence_requirements=all_requirements,
            prepared_images=prepared_images,
            claim_text_risk_flags=detect_prompt_injection_flags(row.get("user_claim", "")),
        )
        total_chars += len(build_text_prompt(context))
    return int(math.ceil(total_chars / 4))


def _token_estimate_from_summary(
    cfg: AppConfig,
    strategy: EvalStrategy,
    sample_rows: list[dict[str, str]],
    summary: dict[str, object],
) -> TokenEstimate:
    prompt_tokens = int(summary.get("prompt_tokens") or 0)
    completion_tokens = int(summary.get("completion_tokens") or 0)
    calls_by_model = dict(summary.get("calls_by_model") or {})
    if prompt_tokens or completion_tokens:
        return TokenEstimate(
            source=str(summary.get("token_source") or "fresh provider metadata"),
            sample_prompt_tokens=prompt_tokens,
            sample_completion_tokens=completion_tokens,
            sample_cached_tokens=int(summary.get("cached_tokens") or 0),
            sample_cache_write_tokens=int(summary.get("cache_write_tokens") or 0),
            sample_latency_ms=int(summary.get("latency_ms") or 0),
            calls_by_model=calls_by_model,
        )
    if strategy.provider == "none" or cfg.paths is None:
        return TokenEstimate(
            source="no provider tokens",
            sample_prompt_tokens=0,
            sample_completion_tokens=0,
            sample_cached_tokens=0,
            sample_cache_write_tokens=0,
            sample_latency_ms=0,
            calls_by_model={},
        )
    estimated_prompt_tokens = _estimate_prompt_size_tokens(sample_rows, cfg.paths)
    estimated_completion_tokens = len(sample_rows) * max(1, cfg.max_output_tokens)
    return TokenEstimate(
        source="approximate prompt-size estimate",
        sample_prompt_tokens=estimated_prompt_tokens,
        sample_completion_tokens=estimated_completion_tokens,
        sample_cached_tokens=0,
        sample_cache_write_tokens=0,
        sample_latency_ms=0,
        calls_by_model={
            (strategy.provider, strategy.model): {
                "calls": len(sample_rows),
                "prompt_tokens": estimated_prompt_tokens,
                "completion_tokens": estimated_completion_tokens,
            }
        },
    )


def _price_warning(
    strategy: EvalStrategy,
    model_prices: dict[tuple[str, str], tuple[float, float]],
) -> str:
    if strategy.provider == "none":
        return ""
    key = (strategy.provider.strip().lower(), strategy.model.strip())
    if key not in model_prices:
        return f"No price configured for {strategy.provider}/{strategy.model}; cost may be underestimated."
    return ""


def _build_strategy_result(
    strategy: EvalStrategy,
    run_dir: Path,
    predictions: list[dict[str, str]],
    expected: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    fields: list[str],
    cfg: AppConfig,
    model_prices: dict[tuple[str, str], tuple[float, float]],
) -> StrategyResult:
    metrics, errors = compare_rows(expected, predictions, fields=fields)
    predictions_path = run_dir / "sample_predictions.csv"
    errors_path = run_dir / "errors.csv"
    metrics_path = run_dir / "metrics.json"
    log_path = run_dir / "run.jsonl"
    _write_predictions_csv(predictions_path, predictions)
    write_errors_csv(errors_path, errors)
    write_metrics_json(metrics_path, metrics)
    summary = _latest_run_provider_summary(log_path)
    token_estimate = _token_estimate_from_summary(cfg, strategy, expected, summary)
    row_scale = (len(test_rows) / len(expected)) if expected else 0.0
    projected_prompt_tokens = int(round(token_estimate.sample_prompt_tokens * row_scale))
    projected_completion_tokens = int(round(token_estimate.sample_completion_tokens * row_scale))
    estimated_cost = _estimate_projected_cost(
        token_estimate.calls_by_model,
        model_prices,
        default_input=0.0,
        default_output=0.0,
        row_scale=row_scale,
        fallback_prompt_tokens=projected_prompt_tokens,
        fallback_completion_tokens=projected_completion_tokens,
    )
    token_call_count = sum(int(usage.get("calls", 0)) for usage in token_estimate.calls_by_model.values())
    avg_latency_seconds = (
        token_estimate.sample_latency_ms / token_call_count / 1000
        if token_call_count
        else 0.0
    )
    observed_provider = str(summary.get("observed_provider") or "unknown")
    test_model_calls = 0 if observed_provider in {"none", "unknown"} else len(test_rows)
    return StrategyResult(
        strategy=strategy,
        run_dir=run_dir,
        predictions_path=predictions_path,
        errors_path=errors_path,
        metrics_path=metrics_path,
        log_path=log_path,
        metrics=metrics,
        errors=errors,
        run_summary={**summary, "test_model_calls": test_model_calls},
        token_estimate=token_estimate,
        estimated_full_test_cost=estimated_cost,
        projected_prompt_tokens=projected_prompt_tokens,
        projected_completion_tokens=projected_completion_tokens,
        estimated_runtime_seconds=avg_latency_seconds * test_model_calls,
        price_warning=_price_warning(strategy, model_prices),
    )


def _select_final_strategy(
    strategy_results: list[StrategyResult],
    final_strategy_name: str,
) -> tuple[StrategyResult, str]:
    if final_strategy_name:
        for result in strategy_results:
            if result.strategy.name == final_strategy_name:
                return result, "Selected by FINAL_STRATEGY/--final-strategy."
        raise ValueError(f"FINAL_STRATEGY did not match any evaluated strategy: {final_strategy_name}")
    selected = max(strategy_results, key=lambda result: _strategy_score(result.metrics))
    return selected, "Selected by weighted sample score."


def _latest_run_provider_summary(log_path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "fallback_used": False,
        "observed_provider": "unknown",
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": 0,
        "calls_by_model": {},
        "backup_reasons": {},
        "primary_provider_calls": 0,
        "backup_provider_calls": 0,
        "fallback_rows": 0,
        "max_concurrency": 1,
        "rate_limit_waits": 0,
        "run_total_duration_ms": 0,
        "cache_hits": 0,
        "token_source": "unavailable",
    }
    if not log_path.exists():
        return summary
    providers: set[str] = set()
    model_calls = 0
    fallback_used = False
    primary_provider = "unknown"
    saw_two_pass_stage = False
    calls_by_model: dict[tuple[str, str], dict[str, int]] = {}
    backup_reasons: dict[str, int] = {}
    primary_provider_calls = 0
    backup_provider_calls = 0
    fallback_rows = 0
    rate_limit_waits = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "run_started":
            providers = set()
            model_calls = 0
            primary_provider = str(record.get("provider") or "unknown").strip().lower()
            saw_two_pass_stage = False
            calls_by_model = {}
            backup_reasons = {}
            primary_provider_calls = 0
            backup_provider_calls = 0
            fallback_rows = 0
            rate_limit_waits = 0
            summary["prompt_tokens"] = 0
            summary["completion_tokens"] = 0
            summary["cached_tokens"] = 0
            summary["cache_write_tokens"] = 0
            summary["latency_ms"] = 0
            summary["token_source"] = "unavailable"
            fallback_used = False
        if record.get("event") == "provider_fallback_used":
            fallback_used = True
        if record.get("event") == "rate_limiter_wait":
            rate_limit_waits += 1
        if record.get("event") == "run_completed":
            summary["max_concurrency"] = int(record.get("max_concurrency") or 1)
            summary["run_total_duration_ms"] = int(record.get("total_duration_ms") or 0)
            summary["cache_hits"] = int(record.get("cache_hits") or 0)
        if record.get("event") == "claim_completed":
            if record.get("backup_used") is True:
                reason = str(record.get("backup_reason") or "unknown_provider_error")
                backup_reasons[reason] = backup_reasons.get(reason, 0) + 1
        if record.get("event") == "provider_error":
            provider = str(record.get("provider") or "").strip().lower() or "unknown"
            providers.add(provider)
            if provider != "none":
                model_calls += 1
                if provider == primary_provider:
                    primary_provider_calls += 1
                else:
                    backup_provider_calls += 1
        if record.get("event") == "two_pass_stage_response":
            saw_two_pass_stage = True
            provider = str(record.get("provider") or "").strip().lower() or "unknown"
            model_name = str(record.get("model") or "").strip()
            providers.add(provider)
            if provider != "none":
                model_calls += 1
                if provider == primary_provider:
                    primary_provider_calls += 1
                else:
                    backup_provider_calls += 1
                key = (provider, model_name)
                if key not in calls_by_model:
                    calls_by_model[key] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
                calls_by_model[key]["calls"] += 1
                calls_by_model[key]["prompt_tokens"] += int(record.get("prompt_tokens") or 0)
                calls_by_model[key]["completion_tokens"] += int(record.get("completion_tokens") or 0)
                summary["prompt_tokens"] = int(summary["prompt_tokens"]) + int(record.get("prompt_tokens") or 0)
                summary["completion_tokens"] = int(summary["completion_tokens"]) + int(record.get("completion_tokens") or 0)
                summary["cached_tokens"] = int(summary["cached_tokens"]) + int(record.get("cached_tokens") or 0)
                summary["latency_ms"] = int(summary["latency_ms"]) + int(record.get("duration_ms") or 0)
                if not record.get("error_category"):
                    summary["token_source"] = "fresh provider metadata"
        if record.get("event") == "provider_response":
            provider = str(record.get("provider") or "").strip().lower() or "unknown"
            model_name = str(record.get("model") or "").strip()
            providers.add(provider)
            if record.get("used_fallback") is True:
                fallback_used = True
                fallback_rows += 1
            elif provider != "none" and not saw_two_pass_stage:
                is_cache_hit = record.get("cache_hit") is True
                if not is_cache_hit:
                    model_calls += 1
                    if provider == primary_provider:
                        primary_provider_calls += 1
                    else:
                        backup_provider_calls += 1
                key = (provider, model_name)
                if key not in calls_by_model:
                    calls_by_model[key] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
                calls_by_model[key]["calls"] += 1
                calls_by_model[key]["prompt_tokens"] += int(record.get("prompt_tokens") or 0)
                calls_by_model[key]["completion_tokens"] += int(record.get("completion_tokens") or 0)
                summary["prompt_tokens"] = int(summary["prompt_tokens"]) + int(record.get("prompt_tokens") or 0)
                summary["completion_tokens"] = int(summary["completion_tokens"]) + int(record.get("completion_tokens") or 0)
                summary["cached_tokens"] = int(summary["cached_tokens"]) + int(record.get("cached_tokens") or 0)
                summary["cache_write_tokens"] = int(summary["cache_write_tokens"]) + int(record.get("cache_creation_input_tokens") or 0)
                summary["latency_ms"] = int(summary["latency_ms"]) + int(record.get("duration_ms") or 0)
                if not is_cache_hit:
                    summary["token_source"] = "fresh provider metadata"
                elif summary["token_source"] == "unavailable" and (
                    int(record.get("prompt_tokens") or 0) or int(record.get("completion_tokens") or 0)
                ):
                    summary["token_source"] = "cached provider metadata"
    observed_provider = "unknown"
    if len(providers) == 1:
        observed_provider = next(iter(providers))
    elif len(providers) > 1:
        observed_provider = "mixed:" + ";".join(sorted(providers))
    summary["fallback_used"] = fallback_used
    summary["observed_provider"] = observed_provider
    summary["model_calls"] = model_calls
    summary["calls_by_model"] = calls_by_model
    summary["backup_reasons"] = backup_reasons
    summary["primary_provider_calls"] = primary_provider_calls
    summary["backup_provider_calls"] = backup_provider_calls
    summary["fallback_rows"] = fallback_rows
    summary["rate_limit_waits"] = rate_limit_waits
    return summary


def main() -> int:
    parser = build_common_arg_parser("Evaluate claim verification on sample_claims.csv.")
    parser.add_argument("--strategy", action="append", default=None)
    parser.add_argument("--final-strategy", default=None)
    args = parser.parse_args()
    load_env_file(args.env)
    cfg = AppConfig.from_env().with_overrides(
        claims=args.claims,
        sample=args.sample,
        history=args.history,
        evidence=args.evidence,
        images=args.images,
        output=args.output,
        log=args.log,
        cache=args.cache,
        provider=args.provider,
        model=args.model,
        retries=args.retries,
        fallback=args.fallback,
        max_concurrency=args.max_concurrency,
        requests_per_minute=args.requests_per_minute,
        backup_max_concurrency=args.backup_max_concurrency,
        prompt_cache_enabled=args.prompt_cache_enabled,
        prompt_cache_retention=args.prompt_cache_retention,
        strategy_mode=args.strategy_mode,
        adjudicator_provider=args.adjudicator_provider,
        adjudicator_model=args.adjudicator_model,
        ignore_cache=args.ignore_cache,
        cache_write_enabled=args.cache_write_enabled,
        save_errors=args.save_errors,
    )
    if cfg.paths is None:
        raise ValueError("AppConfig.paths is required")

    paths = cfg.paths
    default_evaluation_dir = Path(__file__).resolve().parent
    sample_predictions_path = _sample_predictions_path(args.output, default_evaluation_dir)
    evaluation_dir = sample_predictions_path.parent
    expected = load_claim_rows(paths.sample_claims_csv)
    test_rows = load_claim_rows(paths.claims_csv)
    fields = OUTPUT_COLUMNS[4:]
    env_strategy_config = "" if args.strategy else os.environ.get("EVAL_STRATEGIES", "")
    strategies = parse_strategies(args.strategy, env_strategy_config)
    if not strategies:
        strategies = default_strategies(cfg.provider, cfg.model)
    final_strategy_name = (args.final_strategy or os.environ.get("FINAL_STRATEGY", "")).strip()
    model_prices = parse_model_prices(os.environ.get("VLM_MODEL_PRICES", ""))
    runs_dir = evaluation_dir / "runs"
    strategy_results: list[StrategyResult] = []
    for strategy in strategies:
        run_dir = runs_dir / strategy.name
        strategy_cfg = _apply_strategy(cfg, strategy, run_dir)
        predictions = run_predictions(
            strategy_cfg,
            claims_csv=paths.sample_claims_csv,
            output_csv=run_dir / "sample_predictions.csv",
        )
        strategy_results.append(
            _build_strategy_result(
                strategy,
                run_dir,
                predictions,
                expected,
                test_rows,
                fields,
                strategy_cfg,
                model_prices,
            )
        )

    final_result, final_reason = _select_final_strategy(strategy_results, final_strategy_name)
    errors_path = evaluation_dir / "errors.csv"
    metrics_path = evaluation_dir / "metrics.json"
    report_path = evaluation_dir / "evaluation_report.md"
    shutil.copyfile(final_result.predictions_path, sample_predictions_path)
    shutil.copyfile(final_result.errors_path, errors_path)
    shutil.copyfile(final_result.metrics_path, metrics_path)
    _write_multi_strategy_report(
        report_path,
        strategy_results,
        final_result,
        final_reason,
        expected,
        test_rows,
        cfg,
    )

    print(f"Wrote sample predictions to {sample_predictions_path}")
    print(f"Wrote errors to {errors_path}")
    print(f"Wrote metrics to {metrics_path}")
    print(f"Wrote evaluation report to {report_path}")
    print(f"Wrote strategy runs under {runs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
