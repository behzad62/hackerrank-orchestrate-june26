from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

GLASS_WORDS = {"shatter", "shattered", "spiderweb", "cracked glass", "broken glass", "webbed glass"}
SCRATCH_WORDS = {"scratch", "scratched", "scrape", "scraped", "scuff", "scuffed", "paint chip", "paint-chip", "mark"}
CRUSH_WORDS = {"crushed", "smashed", "crumpled", "compressed", "collapsed", "crumple", "caved", "caved in"}
TORN_WORDS = {"torn", "ripped", "tear", "split", "open seam", "open flap", "punctured"}
WATER_WORDS = {"wet", "water", "water damage", "soaked", "damp", "moisture"}
STAIN_WORDS = {"stain", "stained", "discoloration", "discolored"}
MANIPULATION_WORDS = {"editing artifact", "edited", "manipulated", "synthetic"}
NON_ORIGINAL_WORDS = {"stock photo", "watermark", "vecteezy", "screenshot", "listing", "downloaded", "generated image"}
VISIBLE_DAMAGE_WORDS = (
    GLASS_WORDS
    | SCRATCH_WORDS
    | CRUSH_WORDS
    | TORN_WORDS
    | WATER_WORDS
    | STAIN_WORDS
    | {"dent", "dented", "deformation", "damage", "damaged", "broken", "crack", "cracked", "missing"}
)
CONTRADICTION_EVIDENCE_FLAGS = {
    "claim_mismatch",
    "wrong_object",
    "wrong_object_part",
    "non_original_image",
    "damage_not_visible",
}
CONTRADICTION_NOISE_FLAGS = {
    "damage_not_visible",
    "wrong_angle",
    "wrong_object_part",
    "wrong_object",
    "claim_mismatch",
}
QUALITY_SIGNAL_WORDS = {
    "blurry_image": {"blurry", "blurred", "out of focus"},
    "cropped_or_obstructed": {"cropped", "obstructed", "blocked", "partially hidden", "cut off"},
    "low_light_or_glare": {"low light", "dark", "glare", "reflection", "overexposed"},
    "wrong_angle": {"wrong angle", "angle prevents", "not visible from this angle", "side profile", "outside the frame"},
    "wrong_object": {"wrong object", "different object", "different vehicle", "not the claimed object"},
    "wrong_object_part": {"wrong part", "different part", "not the claimed part"},
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
    observations = raw_decision.get("visual_observations") or raw_decision.get("image_observations")
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


def _strip_flag_tokens(text: str) -> str:
    cleaned = text.lower()
    for flag in QUALITY_SIGNAL_WORDS:
        cleaned = cleaned.replace(flag, " ").replace(flag.replace("_", " "), " ")
    for flag in ["claim_mismatch", "possible_manipulation", "non_original_image", "manual_review_required"]:
        cleaned = cleaned.replace(flag, " ").replace(flag.replace("_", " "), " ")
    return cleaned


def _strong_quality_signal(flag: str, evidence_text: str) -> bool:
    clean = _strip_flag_tokens(evidence_text)
    if flag == "possible_manipulation":
        return _contains_any(clean, MANIPULATION_WORDS | NON_ORIGINAL_WORDS)
    if flag == "non_original_image":
        return _contains_any(clean, NON_ORIGINAL_WORDS)
    signal_words = QUALITY_SIGNAL_WORDS.get(flag)
    return bool(signal_words and _contains_any(clean, signal_words))


def _repair_issue_type(
    claim_object: str,
    issue_type: str,
    object_part: str,
    evidence_text: str,
    claim_status: str,
) -> str:
    if claim_status == "not_enough_information":
        return "unknown"

    if object_part == "side_mirror" and issue_type not in {"none", "unknown"}:
        # The challenge samples treat damaged side mirrors as broken_part rather than glass_shatter/scratch.
        return "broken_part"

    if claim_object == "laptop" and object_part == "screen" and issue_type in {"glass_shatter", "broken_part"}:
        return "crack"

    if claim_object == "package":
        # Package label priority matters. Torn/open packaging should not be overwritten by crushed packaging.
        if object_part in {"seal", "box", "package_side", "package_corner"} and _contains_any(evidence_text, TORN_WORDS):
            return "torn_packaging"
        if object_part in {"box", "package_side", "package_corner"} and (
            issue_type in {"dent", "broken_part", "scratch"} or _contains_any(evidence_text, CRUSH_WORDS)
        ):
            return "crushed_packaging"
        if object_part in {"contents", "item"} and _contains_any(evidence_text, {"missing", "absent", "not present"}):
            return "missing_part"
        if _contains_any(evidence_text, WATER_WORDS):
            return "water_damage"
        if issue_type == "water_damage" and _contains_any(evidence_text, STAIN_WORDS) and not _contains_any(evidence_text, WATER_WORDS):
            return "stain"

    if issue_type == "water_damage" and _contains_any(evidence_text, STAIN_WORDS) and not _contains_any(evidence_text, WATER_WORDS):
        return "stain"

    has_scratch = _contains_any(evidence_text, SCRATCH_WORDS)
    has_dent = _contains_any(evidence_text, {"dent", "dented", "deformation", "bent inward", "pushed in"})
    has_crack = _contains_any(evidence_text, {"crack", "cracked", "fracture", "spiderweb"})
    if issue_type in {"dent", "broken_part", "unknown", "crack"} and has_scratch and not has_dent and not has_crack:
        return "scratch"

    return issue_type


def _severity_for_issue(issue_type: str, evidence_text: str, claim_status: str) -> str:
    if claim_status == "not_enough_information":
        return "unknown"
    if issue_type == "none":
        return "none"
    severity = DEFAULT_SEVERITY_BY_ISSUE.get(issue_type, "unknown")
    if severity in {"none", "unknown"}:
        return severity

    clean = _strip_flag_tokens(evidence_text)
    if issue_type in {"scratch", "stain"}:
        return "low"
    if issue_type in {"dent", "crack"}:
        return "medium"
    if issue_type in {"glass_shatter", "missing_part"}:
        return "high"
    if issue_type == "broken_part":
        if _contains_any(clean, {"unusable", "detached", "broken off", "missing"}):
            return "high"
        return "medium"
    if issue_type in {"torn_packaging", "crushed_packaging", "water_damage"}:
        if _contains_any(clean, {"contents exposed", "exposed contents", "item damaged", "contents damaged", "soaked through"}):
            return "high"
        return "medium"
    return severity


def _visible_alternate_damage(raw_decision: dict, evidence_text: str) -> bool:
    observations = raw_decision.get("visual_observations") or raw_decision.get("image_observations")
    if isinstance(observations, list):
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            visible_issues = observation.get("visible_issues") or observation.get("visible_damage")
            if isinstance(visible_issues, list) and any(str(issue).strip() for issue in visible_issues):
                return True
    return _contains_any(evidence_text, VISIBLE_DAMAGE_WORDS)


def _cleanup_flags_for_status(flags: list[str], claim_status: str, issue_type: str, evidence_text: str, repairs: list[dict[str, str]]) -> list[str]:
    output = list(flags)

    for flag in ["possible_manipulation", "non_original_image"]:
        if flag in output and not _strong_quality_signal(flag, evidence_text):
            output.remove(flag)
            _append_repair(repairs, "risk_flags", flag, "removed", f"weak_{flag}_signal")

    if _contains_any(_strip_flag_tokens(evidence_text), NON_ORIGINAL_WORDS) and "non_original_image" not in output:
        output.append("non_original_image")
        _append_repair(repairs, "risk_flags", "missing", "non_original_image", "non_original_image_signal")

    if claim_status == "supported":
        for flag in list(CONTRADICTION_NOISE_FLAGS):
            if flag in output and not _strong_quality_signal(flag, evidence_text):
                output.remove(flag)
                _append_repair(repairs, "risk_flags", flag, "removed", "supported_claim_noise_flag")

    if claim_status == "contradicted" and issue_type == "none" and "damage_not_visible" not in output:
        output.append("damage_not_visible")
        _append_repair(repairs, "risk_flags", "missing", "damage_not_visible", "contradicted_no_visible_issue")

    for flag in ["wrong_angle", "wrong_object", "wrong_object_part", "blurry_image", "cropped_or_obstructed", "low_light_or_glare"]:
        if flag in output and not _strong_quality_signal(flag, evidence_text) and claim_status != "not_enough_information":
            output.remove(flag)
            _append_repair(repairs, "risk_flags", flag, "removed", "weak_quality_signal")

    if any(flag in output for flag in {"possible_manipulation", "non_original_image", "text_instruction_present", "user_history_risk"}):
        output.append("manual_review_required")

    return _ordered_flags(output)


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
    issue_type = _repair_issue_type(claim_object, issue_type, object_part, evidence_text, claim_status)
    _append_repair(repairs, "issue_type", original_issue_type, issue_type, "contest_issue_type_calibration")

    flags = [flag for flag in risk_flags if flag != "none"]
    flags = _cleanup_flags_for_status(flags, claim_status, issue_type, evidence_text, repairs)

    visible_mismatch = "claim_mismatch" in flags and valid_image and _visible_alternate_damage(raw_decision, evidence_text)
    if visible_mismatch and claim_status == "not_enough_information" and "wrong_object" not in flags:
        _append_repair(repairs, "claim_status", claim_status, "contradicted", "visible_claim_mismatch")
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
        if issue_type != "unknown":
            _append_repair(repairs, "issue_type", issue_type, "unknown", "not_enough_information")
            issue_type = "unknown"
        if severity != "unknown":
            _append_repair(repairs, "severity", severity, "unknown", "not_enough_information")
            severity = "unknown"
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

    flags = _cleanup_flags_for_status([flag for flag in flags if flag != "none"], claim_status, issue_type, evidence_text, repairs)
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
