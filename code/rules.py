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
    | {"dent", "dented", "deformation", "damage", "damaged", "broken", "crack", "cracked", "missing", "impact"}
)
ABSENCE_WORDS = {"no damage", "not visible", "absent", "missing evidence", "cannot see", "not shown", "no visible"}
NO_EVIDENCE_WORDS = {
    "cannot verify",
    "cannot be verified",
    "does not provide visible evidence",
    "no usable visual evidence",
    "no visual evidence",
    "not enough visual evidence",
    "too cropped to evaluate",
    "too cropped",
    "does not show the claimed",
    "claimed part is not visible",
}
MISMATCH_WORDS = {
    "mismatch",
    "different part",
    "wrong part",
    "different object",
    "wrong object",
    "different vehicle",
    "different car",
    "not the claimed",
    "rather than the",
    "instead of the",
    "stock photo",
    "watermark",
    "vecteezy",
}
SUPPORT_WORDS = {"clearly shows", "plainly observable", "visible", "consistent with", "matching", "supports the claim", "directly shows"}
MINOR_SEVERITY_WORDS = {
    "small dent",
    "minor dent",
    "small depression",
    "minor depression",
    "slight dent",
    "shallow dent",
    "minor surface",
    "small surface",
}
PACKAGE_CONTENTS_UNCERTAIN_WORDS = {
    "no ordered product",
    "no product or item",
    "only crumpled newspaper",
    "only filler",
    "contents are unclear",
    "cannot verify whether anything is missing",
}
TRACKPAD_MINOR_MARK_WORDS = {"minor surface mark", "small surface mark", "minor mark", "small mark"}
VISIBLE_INSTRUCTION_WORDS = {"approve this claim", "approved claim", "accept this claim"}
TAMPER_LABEL_WORDS = {"void/tamper", "tamper evident", "do not accept"}
NEITHER_IMAGE_WORDS = {"neither img", "neither image", "neither photo", "neither picture"}
FINAL_DECISION_SIGNAL_FIELDS = {
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
}
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
    "cropped_or_obstructed": {"cropped", "obstructed", "blocked", "partially hidden", "cut off", "only crumpled newspaper", "only filler", "contents are unclear"},
    "low_light_or_glare": {"low light", "dark", "glare", "reflection", "overexposed"},
    "wrong_angle": {"wrong angle", "angle prevents", "not visible from this angle", "side profile", "outside the frame", "does not provide visible evidence", "claimed part is not visible"},
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


def _final_decision_signal_text(value: Any) -> str:
    source = value
    if isinstance(value, dict) and isinstance(value.get("decision"), dict):
        source = value["decision"]
    if not isinstance(source, dict):
        return _flatten_text(source)
    return _flatten_text({field: source.get(field) for field in FINAL_DECISION_SIGNAL_FIELDS})


def _contains_any(text: str, words: set[str] | tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _ordered_flags(flags: list[str]) -> list[str]:
    output: list[str] = []
    for flag in flags:
        if flag and flag != "none" and flag not in output:
            output.append(flag)
    return output or ["none"]


def _split_ids(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip() and part.strip() != "none"]


def _ordered_valid_ids(ids: list[str], available_image_ids: list[str]) -> str:
    valid = set(available_image_ids)
    output: list[str] = []
    for raw_id in ids:
        image_id = Path(str(raw_id)).stem
        if image_id in valid and image_id not in output:
            output.append(image_id)
    return ";".join(output) if output else "none"


def _collect_observations(value: Any) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key in ("visual_observations", "image_observations"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                observations.extend(item for item in candidate if isinstance(item, dict))
        for nested_key in ("decision", "primary_decision", "candidate_decision", "adjudicator_decision", "visual_facts"):
            nested = value.get(nested_key)
            if nested is not None and nested is not value:
                observations.extend(_collect_observations(nested))
    elif isinstance(value, list):
        for item in value:
            observations.extend(_collect_observations(item))
    return observations


def _observation_image_id(observation: dict[str, Any]) -> str:
    return Path(str(observation.get("image_id") or "")).stem


def _observation_has_visible_issue(observation: dict[str, Any]) -> bool:
    issues = observation.get("visible_issues")
    damage = observation.get("visible_damage")
    text = _flatten_text({"visible_issues": issues, "visible_damage": damage}).lower()
    if not text:
        return False
    if _contains_any(text, ABSENCE_WORDS):
        return False
    if isinstance(issues, list) and any(str(issue).strip() and str(issue).strip() not in {"none", "unknown"} for issue in issues):
        return True
    if isinstance(damage, list) and any(str(item).strip() for item in damage):
        return True
    return _contains_any(text, VISIBLE_DAMAGE_WORDS)


def _observation_supports_contradiction(observation: dict[str, Any], issue_type: str, risk_flags: list[str]) -> bool:
    text = _flatten_text(observation).lower()
    quality = _flatten_text(observation.get("quality_issues", [])).lower()
    if issue_type == "none" and (_contains_any(text, ABSENCE_WORDS) or "damage_not_visible" in risk_flags):
        return True
    if any(flag in quality or flag.replace("_", " ") in quality for flag in CONTRADICTION_EVIDENCE_FLAGS):
        return True
    if _contains_any(text, MISMATCH_WORDS):
        return True
    if _observation_has_visible_issue(observation) and "claim_mismatch" in risk_flags:
        return True
    return False


def _ids_from_observations(raw_decision: dict, available_image_ids: list[str]) -> str:
    ids = [_observation_image_id(obs) for obs in _collect_observations(raw_decision)]
    if not ids and len(available_image_ids) == 1:
        ids.append(available_image_ids[0])
    return _ordered_valid_ids(ids, available_image_ids)


def _repair_supporting_image_ids(
    *,
    claim_status: str,
    issue_type: str,
    risk_flags: list[str],
    supporting_image_ids: str,
    available_image_ids: list[str],
    raw_decision: dict,
    valid_image: bool,
    repairs: list[dict[str, str]],
) -> str:
    if claim_status == "not_enough_information":
        _append_repair(repairs, "supporting_image_ids", supporting_image_ids, "none", "not_enough_information")
        return "none"

    observations = _collect_observations(raw_decision)
    current_ids = _split_ids(supporting_image_ids)
    repaired_ids: list[str] = []

    if claim_status == "supported":
        for observation in observations:
            image_id = _observation_image_id(observation)
            if image_id and _observation_has_visible_issue(observation):
                repaired_ids.append(image_id)
        if not repaired_ids:
            repaired_ids = current_ids
    elif claim_status == "contradicted":
        for observation in observations:
            image_id = _observation_image_id(observation)
            if image_id and _observation_supports_contradiction(observation, issue_type, risk_flags):
                repaired_ids.append(image_id)
        if not repaired_ids:
            repaired_ids = current_ids
        if not repaired_ids and valid_image:
            repaired_ids = _split_ids(_ids_from_observations(raw_decision, available_image_ids))

    repaired = _ordered_valid_ids(repaired_ids, available_image_ids)
    if repaired == "none" and claim_status == "contradicted" and valid_image and len(available_image_ids) == 1:
        repaired = available_image_ids[0]
    _append_repair(repairs, "supporting_image_ids", supporting_image_ids, repaired, "direct_decision_evidence_images")
    return repaired


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
    if flag == "claim_mismatch":
        return _contains_any(clean, MISMATCH_WORDS) or (
            _contains_any(clean, NEITHER_IMAGE_WORDS) and _has_no_evidence_signal(clean)
        )
    if flag == "damage_not_visible":
        return _contains_any(clean, ABSENCE_WORDS | NO_EVIDENCE_WORDS | PACKAGE_CONTENTS_UNCERTAIN_WORDS)
    if flag == "wrong_object":
        return _contains_any(clean, {"wrong object", "different object", "different vehicle", "different car", "rather than the", "instead of the", "not the claimed object"})
    signal_words = QUALITY_SIGNAL_WORDS.get(flag)
    return bool(signal_words and _contains_any(clean, signal_words))


def _add_flag(flags: list[str], flag: str, repairs: list[dict[str, str]], reason: str) -> None:
    if flag not in flags:
        flags.append(flag)
        _append_repair(repairs, "risk_flags", "missing", flag, reason)


def _has_no_evidence_signal(evidence_text: str) -> bool:
    return _contains_any(evidence_text, ABSENCE_WORDS | NO_EVIDENCE_WORDS)


def _augment_flags_from_evidence(
    *,
    flags: list[str],
    evidence_text: str,
    claim_object: str,
    object_part: str,
    issue_type: str,
    repairs: list[dict[str, str]],
) -> list[str]:
    output = list(flags)
    clean = _strip_flag_tokens(evidence_text)

    if _contains_any(clean, NON_ORIGINAL_WORDS):
        _add_flag(output, "non_original_image", repairs, "non_original_image_signal")
    if _contains_any(clean, MISMATCH_WORDS):
        _add_flag(output, "claim_mismatch", repairs, "mismatch_signal")
        if _contains_any(clean, {"wrong object", "different object", "different vehicle", "different car", "rather than the", "instead of the"}):
            _add_flag(output, "wrong_object", repairs, "wrong_object_signal")
    if _contains_any(clean, NEITHER_IMAGE_WORDS) and _has_no_evidence_signal(clean):
        _add_flag(output, "claim_mismatch", repairs, "neither_image_supports_claim_signal")
    if _has_no_evidence_signal(clean):
        _add_flag(output, "damage_not_visible", repairs, "no_visible_evidence_signal")
        if object_part not in {"unknown", "none"} and _contains_any(clean, {"not visible", "not shown", "does not provide visible evidence"}):
            _add_flag(output, "wrong_angle", repairs, "claimed_part_not_visible_signal")
    if (
        claim_object == "package"
        and object_part == "contents"
        and issue_type == "missing_part"
        and _contains_any(clean, PACKAGE_CONTENTS_UNCERTAIN_WORDS)
    ):
        _add_flag(output, "cropped_or_obstructed", repairs, "package_contents_not_verifiable")
        _add_flag(output, "damage_not_visible", repairs, "package_contents_not_verifiable")
        _add_flag(output, "manual_review_required", repairs, "package_contents_not_verifiable")
    return _ordered_flags(output)


def _infer_issue_from_evidence(claim_object: str, object_part: str, evidence_text: str) -> str:
    if object_part == "side_mirror" and _contains_any(evidence_text, VISIBLE_DAMAGE_WORDS | GLASS_WORDS):
        return "broken_part"
    if claim_object == "laptop" and object_part == "screen" and _contains_any(evidence_text, GLASS_WORDS | {"crack", "cracked", "fracture"}):
        return "crack"
    if claim_object == "package":
        if _contains_any(evidence_text, TORN_WORDS):
            return "torn_packaging"
        if _contains_any(evidence_text, CRUSH_WORDS):
            return "crushed_packaging"
        if _contains_any(evidence_text, WATER_WORDS):
            return "water_damage"
        if _contains_any(evidence_text, STAIN_WORDS):
            return "stain"
        if _contains_any(evidence_text, {"missing", "absent"}):
            return "missing_part"
    if _contains_any(evidence_text, GLASS_WORDS):
        return "glass_shatter" if object_part in {"windshield"} else "crack"
    if _contains_any(evidence_text, {"crack", "cracked", "fracture"}):
        return "crack"
    if _contains_any(evidence_text, {"dent", "dented", "deformation", "pushed in", "caved"}):
        return "dent"
    if _contains_any(evidence_text, SCRATCH_WORDS):
        return "scratch"
    if _contains_any(evidence_text, {"heavily damaged", "severe damage", "front-end damage", "broken", "damaged car"}):
        return "broken_part"
    return "unknown"


def _repair_issue_type(
    claim_object: str,
    issue_type: str,
    object_part: str,
    evidence_text: str,
    claim_status: str,
) -> str:
    if claim_status == "not_enough_information":
        return "unknown"
    if claim_status == "contradicted" and issue_type == "none":
        return "none"

    if object_part == "side_mirror" and issue_type not in {"none", "unknown"}:
        return "broken_part"

    if claim_object == "laptop" and object_part == "screen" and issue_type in {"glass_shatter", "broken_part"}:
        return "crack"

    if claim_object == "package":
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
    if issue_type == "dent":
        if _contains_any(clean, MINOR_SEVERITY_WORDS):
            return "low"
        return "medium"
    if issue_type == "crack":
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
    observations = _collect_observations(raw_decision)
    for observation in observations:
        if _observation_has_visible_issue(observation):
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


def _has_support_signal(evidence_text: str, supporting_image_ids: str, issue_type: str) -> bool:
    if _has_no_evidence_signal(evidence_text):
        return False
    if issue_type == "missing_part" and _contains_any(evidence_text, PACKAGE_CONTENTS_UNCERTAIN_WORDS):
        return False
    if not _contains_any(evidence_text, SUPPORT_WORDS):
        return False
    return _contains_any(evidence_text, SUPPORT_WORDS) and _contains_any(evidence_text, VISIBLE_DAMAGE_WORDS)


def _has_contradiction_signal(evidence_text: str, risk_flags: list[str]) -> bool:
    return bool(set(risk_flags) & {"claim_mismatch", "non_original_image", "wrong_object"}) or _contains_any(evidence_text, MISMATCH_WORDS)


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
    signal_text = _final_decision_signal_text(raw_decision).lower() or evidence_text

    flags = [flag for flag in risk_flags if flag != "none"]
    flags = _augment_flags_from_evidence(
        flags=flags,
        evidence_text=signal_text,
        claim_object=claim_object,
        object_part=object_part,
        issue_type=issue_type,
        repairs=repairs,
    )
    flags = _cleanup_flags_for_status(flags, claim_status, issue_type, signal_text, repairs)

    if claim_status == "supported":
        clean = _strip_flag_tokens(signal_text)
        if (
            claim_object == "package"
            and object_part == "contents"
            and issue_type == "missing_part"
            and _contains_any(clean, PACKAGE_CONTENTS_UNCERTAIN_WORDS)
        ):
            _append_repair(repairs, "claim_status", claim_status, "not_enough_information", "package_contents_not_verifiable")
            claim_status = "not_enough_information"
            evidence_standard_met = False
            valid_image = False
            issue_type = "unknown"
        elif (
            claim_object == "package"
            and object_part == "seal"
            and issue_type == "torn_packaging"
            and "text_instruction_present" in flags
            and _contains_any(clean, VISIBLE_INSTRUCTION_WORDS | TAMPER_LABEL_WORDS)
        ):
            _append_repair(repairs, "claim_status", claim_status, "contradicted", "instruction_text_package_seal_support")
            claim_status = "contradicted"
            issue_type = "none"
            evidence_standard_met = True
            valid_image = True
            _add_flag(flags, "damage_not_visible", repairs, "instruction_text_package_seal_support")
        elif (
            claim_object == "laptop"
            and object_part == "trackpad"
            and issue_type == "scratch"
            and _contains_any(clean, TRACKPAD_MINOR_MARK_WORDS)
        ):
            _append_repair(repairs, "claim_status", claim_status, "contradicted", "minor_trackpad_mark_not_claim_damage")
            claim_status = "contradicted"
            issue_type = "none"
            evidence_standard_met = True
            valid_image = True
            _add_flag(flags, "damage_not_visible", repairs, "minor_trackpad_mark_not_claim_damage")
        elif (
            ({"non_original_image", "wrong_object"} & set(flags))
            or ("claim_mismatch" in flags and _contains_any(clean, NEITHER_IMAGE_WORDS))
        ) and _has_contradiction_signal(signal_text, flags):
            _append_repair(repairs, "claim_status", claim_status, "contradicted", "supported_with_mismatch_signal")
            claim_status = "contradicted"
            evidence_standard_met = True
            valid_image = True
            if issue_type == "unknown":
                inferred = _infer_issue_from_evidence(claim_object, object_part, signal_text)
                if inferred != "unknown":
                    _append_repair(repairs, "issue_type", issue_type, inferred, "contradiction_visible_issue_inference")
                    issue_type = inferred
        elif _has_no_evidence_signal(signal_text):
            _append_repair(repairs, "claim_status", claim_status, "not_enough_information", "supported_without_visible_evidence")
            claim_status = "not_enough_information"
            evidence_standard_met = False

    if claim_status == "not_enough_information":
        contradiction_signal = _has_contradiction_signal(signal_text, flags)
        support_signal = _has_support_signal(signal_text, supporting_image_ids, issue_type)
        if contradiction_signal:
            _append_repair(repairs, "claim_status", claim_status, "contradicted", "nei_with_mismatch_or_authenticity_evidence")
            claim_status = "contradicted"
            evidence_standard_met = True
            valid_image = True
            if issue_type == "unknown":
                inferred = _infer_issue_from_evidence(claim_object, object_part, signal_text)
                if inferred != "unknown":
                    _append_repair(repairs, "issue_type", issue_type, inferred, "contradiction_visible_issue_inference")
                    issue_type = inferred
        elif support_signal:
            _append_repair(repairs, "claim_status", claim_status, "supported", "nei_with_direct_supporting_evidence")
            claim_status = "supported"
            evidence_standard_met = True
            valid_image = True

    original_issue_type = issue_type
    issue_type = _repair_issue_type(claim_object, issue_type, object_part, signal_text, claim_status)
    _append_repair(repairs, "issue_type", original_issue_type, issue_type, "contest_issue_type_calibration")

    flags = _cleanup_flags_for_status(flags, claim_status, issue_type, signal_text, repairs)

    visible_mismatch = "claim_mismatch" in flags and _visible_alternate_damage(raw_decision, signal_text)
    if visible_mismatch and claim_status == "not_enough_information" and "wrong_object" not in flags:
        _append_repair(repairs, "claim_status", claim_status, "contradicted", "visible_claim_mismatch")
        claim_status = "contradicted"
        evidence_standard_met = True
        valid_image = True

    if claim_status == "supported" and not evidence_standard_met:
        _append_repair(repairs, "evidence_standard_met", evidence_standard_met, True, "supported_claim_implies_evidence")
        evidence_standard_met = True
    if claim_status == "contradicted" and (any(flag in flags for flag in CONTRADICTION_EVIDENCE_FLAGS) or _has_contradiction_signal(signal_text, flags)):
        if not evidence_standard_met:
            _append_repair(repairs, "evidence_standard_met", evidence_standard_met, True, "contradiction_supported_by_image")
        evidence_standard_met = True

    if evidence_standard_met and claim_status in {"supported", "contradicted"} and not valid_image:
        _append_repair(repairs, "valid_image", valid_image, True, "decision_supported_by_visual_evidence")
        valid_image = True

    if issue_type == "none":
        severity_target = "none"
    elif issue_type == "unknown" and claim_status == "contradicted" and _has_contradiction_signal(signal_text, flags):
        severity_target = "low"
    else:
        severity_target = _severity_for_issue(issue_type, signal_text, claim_status)
    _append_repair(repairs, "severity", severity, severity_target, "contest_severity_calibration")
    severity = severity_target

    if claim_status == "not_enough_information":
        if evidence_standard_met:
            _append_repair(repairs, "evidence_standard_met", evidence_standard_met, False, "not_enough_information")
        evidence_standard_met = False
        if issue_type != "unknown":
            _append_repair(repairs, "issue_type", issue_type, "unknown", "not_enough_information")
            issue_type = "unknown"
        if severity != "unknown":
            _append_repair(repairs, "severity", severity, "unknown", "not_enough_information")
            severity = "unknown"

    flags = _cleanup_flags_for_status([flag for flag in flags if flag != "none"], claim_status, issue_type, signal_text, repairs)
    supporting_image_ids = _repair_supporting_image_ids(
        claim_status=claim_status,
        issue_type=issue_type,
        risk_flags=flags,
        supporting_image_ids=supporting_image_ids,
        available_image_ids=available_image_ids,
        raw_decision=raw_decision,
        valid_image=valid_image,
        repairs=repairs,
    )

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
