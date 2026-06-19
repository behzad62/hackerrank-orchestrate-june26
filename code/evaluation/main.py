from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from config import AppConfig, build_common_arg_parser, load_env_file
from data import load_claim_rows
from evaluation.metrics import compare_rows, write_errors_csv, write_metrics_json
from runner import run_predictions
from schemas import OUTPUT_COLUMNS


HIGH_VALUE_FIELDS = [
    "claim_status",
    "issue_type",
    "object_part",
    "evidence_standard_met",
    "valid_image",
    "severity",
]


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
) -> None:
    sample_images = _count_images(sample_rows)
    test_images = _count_images(test_rows)
    scores = metrics.get("risk_flag_scores", {})
    image_scores = metrics.get("supporting_image_id_scores", {})
    if provider == "none":
        fallback_note = "No VLM provider was configured, so images were not inspected and model cost is $0."
    elif fallback_used:
        fallback_note = (
            "A VLM provider was configured, but no-vision fallback was observed for at least one row. "
            "Successful provider rows may have inspected images; fallback rows did not."
        )
    else:
        fallback_note = "A configured VLM provider was used for image inspection."

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

Test set:
- Rows: {len(test_rows)}
- Images: {test_images}
- Expected model calls: {test_model_calls}

The system uses one multimodal call per claim row when a real VLM provider is configured. Images for the same claim are submitted together so the model can compare overview and close-up evidence.

Pricing assumptions:
- Provider pricing varies by selected model.
- Use provider token accounting from logs/provider metadata when available.
- With `VLM_PROVIDER=none`, images were not inspected and model cost is $0.
- If fallback is observed during a real-provider run, fallback rows did not receive visual inspection; provider rows may still have token costs.

Runtime and rate limits:
- Calls are sequential by default.
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


def _sample_predictions_path(output_arg: Path | None, default_evaluation_dir: Path) -> Path:
    if output_arg is None:
        return default_evaluation_dir / "sample_predictions.csv"
    if output_arg.exists() and output_arg.is_dir():
        return output_arg / "sample_predictions.csv"
    if output_arg.suffix:
        return output_arg
    return output_arg / "sample_predictions.csv"


def _latest_run_provider_summary(log_path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "fallback_used": False,
        "observed_provider": "unknown",
        "model_calls": 0,
    }
    if not log_path.exists():
        return summary
    providers: set[str] = set()
    model_calls = 0
    fallback_used = False
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "run_started":
            providers = set()
            model_calls = 0
            fallback_used = False
        if record.get("event") == "provider_fallback_used":
            fallback_used = True
        if record.get("event") == "provider_response":
            provider = str(record.get("provider") or "").strip().lower() or "unknown"
            providers.add(provider)
            if record.get("used_fallback") is True:
                fallback_used = True
            elif provider != "none" and record.get("cache_hit") is not True:
                model_calls += 1
    observed_provider = "unknown"
    if len(providers) == 1:
        observed_provider = next(iter(providers))
    elif len(providers) > 1:
        observed_provider = "mixed:" + ";".join(sorted(providers))
    summary["fallback_used"] = fallback_used
    summary["observed_provider"] = observed_provider
    summary["model_calls"] = model_calls
    return summary


def main() -> int:
    parser = build_common_arg_parser("Evaluate claim verification on sample_claims.csv.")
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
        save_errors=args.save_errors,
    )
    if cfg.paths is None:
        raise ValueError("AppConfig.paths is required")

    paths = cfg.paths
    default_evaluation_dir = Path(__file__).resolve().parent
    sample_predictions_path = _sample_predictions_path(args.output, default_evaluation_dir)
    evaluation_dir = sample_predictions_path.parent
    errors_path = evaluation_dir / "errors.csv"
    metrics_path = evaluation_dir / "metrics.json"
    report_path = evaluation_dir / "evaluation_report.md"

    predictions = run_predictions(
        cfg,
        claims_csv=paths.sample_claims_csv,
        output_csv=sample_predictions_path,
    )
    expected = load_claim_rows(paths.sample_claims_csv)
    fields = OUTPUT_COLUMNS[4:]
    metrics, errors = compare_rows(expected, predictions, fields=fields)

    _write_predictions_csv(sample_predictions_path, predictions)
    write_errors_csv(errors_path, errors)
    write_metrics_json(metrics_path, metrics)
    test_rows = load_claim_rows(paths.claims_csv)
    run_summary = _latest_run_provider_summary(paths.logs_dir / "run.jsonl")
    observed_provider = str(run_summary["observed_provider"])
    sample_model_calls = int(run_summary["model_calls"])
    test_model_calls = len(test_rows) if observed_provider not in {"none", "unknown"} and sample_model_calls else 0
    _write_report(
        report_path,
        metrics,
        expected,
        test_rows,
        cfg.provider,
        cfg.model,
        observed_provider=observed_provider,
        fallback_allowed=cfg.allow_no_vision_fallback,
        fallback_used=cfg.provider == "none" or bool(run_summary["fallback_used"]),
        sample_model_calls=sample_model_calls,
        test_model_calls=test_model_calls,
    )

    print(f"Wrote sample predictions to {sample_predictions_path}")
    print(f"Wrote errors to {errors_path}")
    print(f"Wrote metrics to {metrics_path}")
    print(f"Wrote evaluation report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
