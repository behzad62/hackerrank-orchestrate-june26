from __future__ import annotations

import csv
import json
from collections import Counter
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

CORE_DECISION_FIELDS = {
    "claim_status",
    "issue_type",
    "object_part",
    "evidence_standard_met",
    "risk_flags",
    "supporting_image_ids",
    "valid_image",
    "severity",
}


def _flag_set(value: str) -> set[str]:
    return {
        part.strip()
        for part in value.split(";")
        if part.strip() and part.strip() != "none"
    }


def risk_flag_scores(expected: list[str], predicted: list[str]) -> dict[str, float]:
    true_positive = false_positive = false_negative = 0
    total = max(len(expected), len(predicted))
    for idx in range(total):
        exp_set = _flag_set(expected[idx]) if idx < len(expected) else set()
        pred_set = _flag_set(predicted[idx]) if idx < len(predicted) else set()
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


def supporting_image_id_scores(expected: list[str], predicted: list[str]) -> dict[str, float]:
    scores = risk_flag_scores(expected, predicted)
    total = max(len(expected), len(predicted))
    if not total:
        average_jaccard = 1.0
    else:
        overlaps = []
        for idx in range(total):
            exp_set = _flag_set(expected[idx]) if idx < len(expected) else set()
            pred_set = _flag_set(predicted[idx]) if idx < len(predicted) else set()
            union = exp_set | pred_set
            overlaps.append((len(exp_set & pred_set) / len(union)) if union else 1.0)
        average_jaccard = sum(overlaps) / total
    return {**scores, "average_jaccard": average_jaccard}


def core_decision_error_analysis(errors: list[dict[str, str]]) -> dict[str, object]:
    core_errors = [error for error in errors if error.get("field") in CORE_DECISION_FIELDS]
    field_counts = Counter(error.get("field", "unknown") for error in core_errors)
    claim_status_pairs: Counter[tuple[str, str]] = Counter()
    issue_type_pairs: Counter[tuple[str, str]] = Counter()
    severity_pairs: Counter[tuple[str, str]] = Counter()
    risk_flag_false_positives: Counter[str] = Counter()
    risk_flag_false_negatives: Counter[str] = Counter()
    for error in core_errors:
        expected = error.get("expected", "")
        predicted = error.get("predicted", "")
        field = error.get("field")
        if field == "claim_status":
            claim_status_pairs[(expected, predicted)] += 1
        elif field == "issue_type":
            issue_type_pairs[(expected, predicted)] += 1
        elif field == "severity":
            severity_pairs[(expected, predicted)] += 1
        elif field == "risk_flags":
            expected_flags = _flag_set(expected)
            predicted_flags = _flag_set(predicted)
            for flag in sorted(predicted_flags - expected_flags):
                risk_flag_false_positives[flag] += 1
            for flag in sorted(expected_flags - predicted_flags):
                risk_flag_false_negatives[flag] += 1
    return {
        "core_error_count": len(core_errors),
        "field_counts": dict(field_counts),
        "claim_status_pairs": dict(claim_status_pairs),
        "issue_type_pairs": dict(issue_type_pairs),
        "severity_pairs": dict(severity_pairs),
        "risk_flag_false_positives": dict(risk_flag_false_positives),
        "risk_flag_false_negatives": dict(risk_flag_false_negatives),
    }


def justification_quality_metrics(predicted: list[dict[str, str]]) -> dict[str, float]:
    total = len(predicted)
    if not total:
        return {
            "evidence_standard_met_reason_non_empty_rate": 0.0,
            "claim_status_justification_non_empty_rate": 0.0,
            "claim_status_justification_mentions_image_id_rate": 0.0,
            "average_justification_length": 0.0,
        }
    evidence_non_empty = 0
    claim_non_empty = 0
    mentions_image_id = 0
    total_length = 0
    for row in predicted:
        evidence_reason = row.get("evidence_standard_met_reason", "").strip()
        claim_reason = row.get("claim_status_justification", "").strip()
        if evidence_reason:
            evidence_non_empty += 1
        if claim_reason:
            claim_non_empty += 1
        if "img_" in claim_reason.lower():
            mentions_image_id += 1
        total_length += len(claim_reason)
    return {
        "evidence_standard_met_reason_non_empty_rate": evidence_non_empty / total,
        "claim_status_justification_non_empty_rate": claim_non_empty / total,
        "claim_status_justification_mentions_image_id_rate": mentions_image_id / total,
        "average_justification_length": total_length / total,
    }


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
    if "supporting_image_ids" in fields:
        metrics["supporting_image_id_scores"] = supporting_image_id_scores(
            [
                expected[idx].get("supporting_image_ids", "none") if idx < len(expected) else ""
                for idx in range(total)
            ],
            [
                predicted[idx].get("supporting_image_ids", "none") if idx < len(predicted) else ""
                for idx in range(total)
            ],
        )
    metrics["justification_quality"] = justification_quality_metrics(predicted)
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
