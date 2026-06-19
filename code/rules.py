from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GLASS_WORDS = {"shatter", "shattered", "spiderweb", "cracked glass", "broken glass"}
SCRATCH_WORDS = {"scratch", "scrape", "scuff", "paint chip", "mark"}
CRUSH_WORDS = {"crushed", "smashed", "crumpled", "compressed", "collapsed", "crumple"}
TORN_WORDS = {"torn", "ripped", "tear", "split", "open seam", "open flap"}
WATER_WORDS = {"wet", "water", "soaked", "stain", "stained"}
LOWER_WORDS = {"minor", "small", "light", "surface", "tiny", "hairline"}
RAISE_WORDS = {"severe", "large", "unusable", "hanging", "missing", "exposed contents"}
MANIPULATION_WORDS = {"editing artifact", "edited", "manipulated", "photoshop", "synthetic", "generated"}
NON_ORIGINAL_WORDS = {"stock photo", "watermark", "screenshot", "listing", "downloaded", "generated image"}
VISIBLE_DAMAGE_WORDS = (
    GLASS_WORDS
    | SCRATCH_WORDS
    | CRUSH_WORDS
    | TORN_WORDS
    | WATER_WORDS
    | {"dent", "dented", "damage", "broken", "crack", "cracked", "missing"}
)
CONTRADICTION_EVIDENCE_FLAGS = {
    "claim_mismatch",
    "wrong_object",
    "wrong_object_part",
    "non_original_image",
    "damage_not_visible",
}

DEFAULT_SEVERITY_BY_ISSUE = {
    "none": "none",
    "scratch": "low",
    "stain": "low",
    "dent": "medium",
    "crack": "medium",
    "glass_shatter": "high",
    "broken_part": "medium",
    "missing_part": "high",
    "torn_packaging": "medium",
    "crushed_packaging": "medium",
    "water_damage": "medium",
    "unknown": "unknown",
}


@dataclass(frozen=True)
class RepairedDecision:
    issue_type: str
    object_part: str
    claim_status: str
    severity: str
    risk_flags: list[str]
    evidence_standard_met: bool
    valid_image: bool
    supporting_image_ids: str


def _append_repair(
    repairs: list[dict[str, str]],
    field: str,
    original_value: object,
    repaired_value: object,
    reason: str,
) -> None:
    if original_value == repaired_value:
        return
    repairs.append(
        {
            "field": field,
            "original_value": str(original_value).lower(),
            "repaired_value": str(repaired_value).lower(),
            "reason": reason,
        }
    )


def _flatten_text(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            parts.append(_flatten_text(item))
    elif isinstance(value, list):
        for item in value:
            parts.append(_flatten_text(item))
    elif value is not None:
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _contains_any(text: str, words: set[str] | tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _ordered_flags(flags: list[str]) -> list[str]:
    output: list[str] = []
    for flag in flags:
        if flag and flag != "none" and flag not in output:
            output.append(flag)
    return output or ["none"]


def _ids_from_observations(raw_decision: dict, available_image_ids: list[str]) -> str:
    ids: list[str] = []
    observations = raw_decision.get("visual_observations")
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            image_id = Path(str(observation.get("image_id") or "")).stem
            if image_id in available_image_ids and image_id not in ids:
                ids.append(image_id)
    if not ids and len(available_image_ids) == 1:
        ids.append(available_image_ids[0])
    return ";".join(ids) if ids else "none"


def _repair_issue_type(
    claim_object: str,
    issue_type: str,
    object_part: str,
    evidence_text: str,
) -> str:
    if object_part == "side_mirror" and issue_type in {"glass_shatter", "crack"}:
        return "broken_part"
    if claim_object == "laptop" and object_part == "screen" and issue_type == "glass_shatter":
        return "crack"
    if claim_object == "package":
        if object_part in {"box", "package_side", "package_corner"} and (
            issue_type in {"dent", "broken_part"} or _contains_any(evidence_text, CRUSH_WORDS)
        ):
            return "crushed_packaging"
        if object_part in {"seal", "box"} and _contains_any(evidence_text, TORN_WORDS):
            return "torn_packaging"
        if object_part in {"contents", "item"} and ("missing" in evidence_text or "absent" in evidence_text):
            return "missing_part"
        if _contains_any(evidence_text, WATER_WORDS):
            return "water_damage"
    if issue_type in {"dent", "broken_part", "unknown"} and _contains_any(evidence_text, SCRATCH_WORDS):
        return "scratch"
    return issue_type


def _severity_for_issue(issue_type: str, evidence_text: str, claim_status: str) -> str:
    if claim_status == "not_enough_information":
        return "unknown"
    severity = DEFAULT_SEVERITY_BY_ISSUE.get(issue_type, "unknown")
    if severity in {"none", "unknown"}:
        return severity
    levels = ["low", "medium", "high"]
    index = levels.index(severity)
    if _contains_any(evidence_text, LOWER_WORDS):
        index = max(0, index - 1)
    if _contains_any(evidence_text, RAISE_WORDS):
        index = min(len(levels) - 1, index + 1)
    return levels[index]


def _visible_alternate_damage(raw_decision: dict, evidence_text: str) -> bool:
    observations = raw_decision.get("visual_observations")
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            visible_issues = observation.get("visible_issues")
            if isinstance(visible_issues, list) and any(str(issue).strip() for issue in visible_issues):
                return True
    return _contains_any(evidence_text, VISIBLE_DAMAGE_WORDS)


def repair_normalized_decision(
    *,
    claim_object: str,
    issue_type: str,
    object_part: str,
    claim_status: str,
    severity: str,
    risk_flags: list[str],
    evidence_standard_met: bool,
    valid_image: bool,
    supporting_image_ids: str,
    available_image_ids: list[str],
    raw_decision: dict,
    repairs: list[dict[str, str]],
) -> RepairedDecision:
    evidence_text = _flatten_text(raw_decision).lower()

    original_issue_type = issue_type
    issue_type = _repair_issue_type(claim_object, issue_type, object_part, evidence_text)
    _append_repair(repairs, "issue_type", original_issue_type, issue_type, "contest_issue_type_calibration")

    flags = [flag for flag in risk_flags if flag != "none"]
    if "possible_manipulation" in flags and not _contains_any(evidence_text, MANIPULATION_WORDS | NON_ORIGINAL_WORDS):
        flags.remove("possible_manipulation")
        _append_repair(
            repairs,
            "risk_flags",
            "possible_manipulation",
            "removed",
            "weak_possible_manipulation_signal",
        )
    if _contains_any(evidence_text, NON_ORIGINAL_WORDS):
        flags.extend(["non_original_image", "manual_review_required"])
    if "possible_manipulation" in flags or "non_original_image" in flags or "text_instruction_present" in flags:
        flags.append("manual_review_required")
    if "user_history_risk" in flags:
        flags.append("manual_review_required")

    visible_mismatch = "claim_mismatch" in flags and valid_image and _visible_alternate_damage(raw_decision, evidence_text)
    if visible_mismatch and claim_status == "not_enough_information" and "wrong_object" not in flags:
        _append_repair(
            repairs,
            "claim_status",
            claim_status,
            "contradicted",
            "visible_claim_mismatch",
        )
        claim_status = "contradicted"
        evidence_standard_met = True

    if claim_status == "contradicted" and any(flag in flags for flag in CONTRADICTION_EVIDENCE_FLAGS):
        if not evidence_standard_met:
            _append_repair(
                repairs,
                "evidence_standard_met",
                evidence_standard_met,
                True,
                "contradiction_supported_by_image",
            )
        evidence_standard_met = True

    if claim_status == "contradicted" and "wrong_angle" in flags:
        flags.remove("wrong_angle")
        _append_repair(repairs, "risk_flags", "wrong_angle", "removed", "sufficient_to_contradict")

    if issue_type == "none":
        severity_target = "none"
    else:
        severity_target = _severity_for_issue(issue_type, evidence_text, claim_status)
    _append_repair(repairs, "severity", severity, severity_target, "contest_severity_calibration")
    severity = severity_target

    if claim_status == "not_enough_information":
        if supporting_image_ids != "none":
            _append_repair(
                repairs,
                "supporting_image_ids",
                supporting_image_ids,
                "none",
                "not_enough_information",
            )
        supporting_image_ids = "none"
        evidence_standard_met = False
    elif claim_status == "contradicted" and supporting_image_ids == "none" and valid_image:
        repaired_ids = _ids_from_observations(raw_decision, available_image_ids)
        _append_repair(
            repairs,
            "supporting_image_ids",
            supporting_image_ids,
            repaired_ids,
            "contradiction_supported_by_image",
        )
        supporting_image_ids = repaired_ids

    flags = _ordered_flags(flags)
    return RepairedDecision(
        issue_type=issue_type,
        object_part=object_part,
        claim_status=claim_status,
        severity=severity,
        risk_flags=flags,
        evidence_standard_met=evidence_standard_met,
        valid_image=valid_image,
        supporting_image_ids=supporting_image_ids,
    )
