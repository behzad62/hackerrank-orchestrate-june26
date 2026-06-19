from __future__ import annotations

import csv
import json
from pathlib import Path


ERROR_COLUMNS = [
    "row_index",
    "user_id",
    "image_paths",
    "claim_object",
    "user_claim",
    "field",
    "expected",
    "predicted",
    "claim_status_expected",
    "claim_status_predicted",
    "issue_type_expected",
    "issue_type_predicted",
    "object_part_expected",
    "object_part_predicted",
    "risk_flags_expected",
    "risk_flags_predicted",
    "model_summary",
]


def _flag_set(value: str) -> set[str]:
    return {
        part.strip()
        for part in value.split(";")
        if part.strip() and part.strip() != "none"
    }


def risk_flag_scores(expected: list[str], predicted: list[str]) -> dict[str, float]:
    true_positive = false_positive = false_negative = 0
    for exp, pred in zip(expected, predicted):
        exp_set = _flag_set(exp)
        pred_set = _flag_set(pred)
        true_positive += len(exp_set & pred_set)
        false_positive += len(pred_set - exp_set)
        false_negative += len(exp_set - pred_set)

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def compare_rows(
    expected: list[dict[str, str]],
    predicted: list[dict[str, str]],
    fields: list[str],
) -> tuple[dict, list[dict[str, str]]]:
    total = max(len(expected), len(predicted))
    correct = {field: 0 for field in fields}
    errors: list[dict[str, str]] = []

    for idx in range(total):
        exp = expected[idx] if idx < len(expected) else {}
        pred = predicted[idx] if idx < len(predicted) else {}
        missing_expected = idx >= len(expected)
        missing_predicted = idx >= len(predicted)
        for field in fields:
            expected_value = "[missing_row]" if missing_expected else exp.get(field, "")
            predicted_value = "[missing_row]" if missing_predicted else pred.get(field, "")
            if not missing_expected and not missing_predicted and expected_value == predicted_value:
                correct[field] += 1
                continue
            errors.append(
                {
                    "row_index": str(idx + 1),
                    "user_id": exp.get("user_id", pred.get("user_id", "")),
                    "image_paths": exp.get("image_paths", pred.get("image_paths", "")),
                    "claim_object": exp.get("claim_object", pred.get("claim_object", "")),
                    "user_claim": exp.get("user_claim", pred.get("user_claim", "")),
                    "field": field,
                    "expected": expected_value,
                    "predicted": predicted_value,
                    "claim_status_expected": exp.get("claim_status", ""),
                    "claim_status_predicted": pred.get("claim_status", ""),
                    "issue_type_expected": exp.get("issue_type", ""),
                    "issue_type_predicted": pred.get("issue_type", ""),
                    "object_part_expected": exp.get("object_part", ""),
                    "object_part_predicted": pred.get("object_part", ""),
                    "risk_flags_expected": exp.get("risk_flags", ""),
                    "risk_flags_predicted": pred.get("risk_flags", ""),
                    "model_summary": pred.get("claim_status_justification", ""),
                }
            )

    metrics = {
        "rows_expected": len(expected),
        "rows_predicted": len(predicted),
        "rows_compared": total,
        "field_accuracy": {
            field: (correct[field] / total if total else 0.0) for field in fields
        },
        "error_count": len(errors),
    }
    if "risk_flags" in fields:
        metrics["risk_flag_scores"] = risk_flag_scores(
            [
                expected[idx].get("risk_flags", "none") if idx < len(expected) else ""
                for idx in range(total)
            ],
            [
                predicted[idx].get("risk_flags", "none") if idx < len(predicted) else ""
                for idx in range(total)
            ],
        )
    return metrics, errors


def write_errors_csv(path: Path, errors: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ERROR_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(errors)


def write_metrics_json(path: Path, metrics: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
