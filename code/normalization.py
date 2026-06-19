from __future__ import annotations

from pathlib import Path
from typing import Any

from rules import repair_normalized_decision
from schemas import (
    ALLOWED_CLAIM_STATUS,
    ALLOWED_ISSUE_TYPES,
    ALLOWED_OBJECT_PARTS,
    ALLOWED_RISK_FLAGS,
    ALLOWED_SEVERITY,
    OUTPUT_COLUMNS,
    PredictionContext,
    ProviderResult,
    bool_to_csv,
    split_semicolon,
)
from security import merge_risk_flags

ISSUE_REPAIRS = {
    "paint_damage": "scratch",
    "paint": "scratch",
    "shattered_glass": "glass_shatter",
    "broken": "broken_part",
    "missing": "missing_part",
    "water": "water_damage",
}

STATUS_REPAIRS = {
    "supports": "supported",
    "support": "supported",
    "unsupported": "contradicted",
    "insufficient": "not_enough_information",
    "not_enough_info": "not_enough_information",
    "unknown": "not_enough_information",
}

SEVERITY_REPAIRS = {
    "minor": "low",
    "moderate": "medium",
    "severe": "high",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _decision(raw_json: dict[str, Any]) -> dict[str, Any]:
    decision = raw_json.get("decision")
    return decision if isinstance(decision, dict) else raw_json


def _repair_enum(
    value: Any,
    allowed: set[str],
    default: str,
    repairs: dict[str, str],
    field: str,
    repair_log: list[dict[str, str]],
) -> str:
    text = str(value or "").strip().lower()
    text = text.replace(" ", "_").replace("-", "_")
    if text in allowed:
        return text
    repaired = repairs.get(text)
    if repaired in allowed:
        repair_log.append(
            {
                "field": field,
                "original_value": text,
                "repaired_value": repaired,
                "reason": "closest_allowed_enum",
            }
        )
        return repaired
    if text:
        repair_log.append(
            {
                "field": field,
                "original_value": text,
                "repaired_value": default,
                "reason": "invalid_enum_default",
            }
        )
    return default


def _normalize_risk_flags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_flags = split_semicolon(value)
    elif isinstance(value, list):
        raw_flags = [str(item).strip() for item in value]
    else:
        raw_flags = []

    flags: list[str] = []
    for flag in raw_flags:
        normalized = flag.lower().replace(" ", "_").replace("-", "_")
        if normalized in ALLOWED_RISK_FLAGS and normalized != "none" and normalized not in flags:
            flags.append(normalized)
    return flags or ["none"]


def _supporting_ids(value: Any, image_paths: str) -> str:
    valid_ids = {Path(part.strip()).stem for part in image_paths.split(";") if part.strip()}
    if isinstance(value, str):
        raw_ids = split_semicolon(value)
    elif isinstance(value, list):
        raw_ids = [str(item).strip() for item in value]
    else:
        raw_ids = []
    ids = []
    for raw_id in raw_ids:
        image_id = Path(raw_id).stem
        if image_id in valid_ids:
            ids.append(image_id)
    return ";".join(dict.fromkeys(ids)) if ids else "none"


def _history_flags(context: PredictionContext) -> list[str]:
    flags = context.user_history.get("history_flags", "")
    return [flag for flag in split_semicolon(flags) if flag in {"user_history_risk", "manual_review_required"}]


def normalize_provider_result(
    context: PredictionContext,
    result: ProviderResult,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    repairs: list[dict[str, str]] = []
    decision = _decision(result.raw_json)
    claim_object = context.row.get("claim_object", "car")

    issue_type = _repair_enum(
        decision.get("issue_type"),
        ALLOWED_ISSUE_TYPES,
        "unknown",
        ISSUE_REPAIRS,
        "issue_type",
        repairs,
    )
    object_part = _repair_enum(
        decision.get("object_part"),
        ALLOWED_OBJECT_PARTS.get(claim_object, {"unknown"}),
        "unknown",
        {},
        "object_part",
        repairs,
    )
    claim_status = _repair_enum(
        decision.get("claim_status"),
        ALLOWED_CLAIM_STATUS,
        "not_enough_information",
        STATUS_REPAIRS,
        "claim_status",
        repairs,
    )
    severity = _repair_enum(
        decision.get("severity"),
        ALLOWED_SEVERITY,
        "unknown",
        SEVERITY_REPAIRS,
        "severity",
        repairs,
    )

    evidence_standard_met = _as_bool(decision.get("evidence_standard_met", False))
    valid_image = _as_bool(decision.get("valid_image", False))
    supporting_image_ids = _supporting_ids(
        decision.get("supporting_image_ids"),
        context.row.get("image_paths", ""),
    )

    if not evidence_standard_met and claim_status == "supported":
        repairs.append(
            {
                "field": "claim_status",
                "original_value": claim_status,
                "repaired_value": "not_enough_information",
                "reason": "evidence_standard_not_met",
            }
        )
        claim_status = "not_enough_information"

    if claim_status == "not_enough_information":
        if supporting_image_ids != "none":
            repairs.append(
                {
                    "field": "supporting_image_ids",
                    "original_value": supporting_image_ids,
                    "repaired_value": "none",
                    "reason": "not_enough_information",
                }
            )
            supporting_image_ids = "none"
        if severity not in {"unknown", "none"}:
            repairs.append(
                {
                    "field": "severity",
                    "original_value": severity,
                    "repaired_value": "unknown",
                    "reason": "not_enough_information",
                }
            )
            severity = "unknown"
        if evidence_standard_met:
            repairs.append(
                {
                    "field": "evidence_standard_met",
                    "original_value": "true",
                    "repaired_value": "false",
                    "reason": "not_enough_information",
                }
            )
            evidence_standard_met = False

    risk_flags = merge_risk_flags(
        _normalize_risk_flags(decision.get("risk_flags")),
        _normalize_risk_flags(context.claim_text_risk_flags),
        _history_flags(context),
    )
    available_image_ids = [image.image_id for image in context.prepared_images]
    if not available_image_ids:
        available_image_ids = [Path(part.strip()).stem for part in context.row.get("image_paths", "").split(";") if part.strip()]
    repaired = repair_normalized_decision(
        claim_object=claim_object,
        issue_type=issue_type,
        object_part=object_part,
        claim_status=claim_status,
        severity=severity,
        risk_flags=risk_flags,
        evidence_standard_met=evidence_standard_met,
        valid_image=valid_image,
        supporting_image_ids=supporting_image_ids,
        available_image_ids=available_image_ids,
        raw_decision=decision,
        repairs=repairs,
    )
    issue_type = repaired.issue_type
    object_part = repaired.object_part
    claim_status = repaired.claim_status
    severity = repaired.severity
    risk_flags = repaired.risk_flags
    evidence_standard_met = repaired.evidence_standard_met
    valid_image = repaired.valid_image
    supporting_image_ids = repaired.supporting_image_ids

    row = {
        "user_id": context.row.get("user_id", ""),
        "image_paths": context.row.get("image_paths", ""),
        "user_claim": context.row.get("user_claim", ""),
        "claim_object": claim_object,
        "evidence_standard_met": bool_to_csv(evidence_standard_met),
        "evidence_standard_met_reason": str(
            decision.get("evidence_standard_met_reason") or "Evidence could not be evaluated."
        )[:500],
        "risk_flags": ";".join(risk_flags),
        "issue_type": issue_type,
        "object_part": object_part,
        "claim_status": claim_status,
        "claim_status_justification": str(
            decision.get("claim_status_justification") or "No visual conclusion was available."
        )[:500],
        "supporting_image_ids": supporting_image_ids,
        "valid_image": bool_to_csv(valid_image),
        "severity": severity,
    }
    return {column: row.get(column, "") for column in OUTPUT_COLUMNS}, repairs
