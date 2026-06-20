from __future__ import annotations

from rules import repair_normalized_decision


def repair_case(**overrides):
    repairs: list[dict[str, str]] = []
    base = {
        "claim_object": "car",
        "issue_type": "unknown",
        "object_part": "unknown",
        "claim_status": "supported",
        "severity": "unknown",
        "risk_flags": ["none"],
        "evidence_standard_met": True,
        "valid_image": True,
        "supporting_image_ids": "img_1",
        "available_image_ids": ["img_1"],
        "raw_decision": {},
        "repairs": repairs,
    }
    base.update(overrides)
    repaired = repair_normalized_decision(**base)
    return repaired, repairs


def test_side_mirror_shattered_maps_to_broken_part():
    repaired, repairs = repair_case(
        object_part="side_mirror",
        issue_type="glass_shatter",
        severity="high",
        raw_decision={
            "claim_status_justification": "img_1 shows the side mirror glass is shattered.",
        },
    )

    assert repaired.issue_type == "broken_part"
    assert repaired.severity == "medium"
    assert any(repair["field"] == "issue_type" for repair in repairs)


def test_laptop_screen_glass_shatter_maps_to_crack():
    repaired, _ = repair_case(
        claim_object="laptop",
        object_part="screen",
        issue_type="glass_shatter",
        raw_decision={"claim_status_justification": "The screen has spiderweb cracked glass."},
    )

    assert repaired.issue_type == "crack"
    assert repaired.severity == "medium"


def test_package_crumpled_box_maps_to_crushed_packaging():
    repaired, _ = repair_case(
        claim_object="package",
        object_part="box",
        issue_type="dent",
        raw_decision={"evidence_standard_met_reason": "The box is visibly crumpled and collapsed."},
    )

    assert repaired.issue_type == "crushed_packaging"
    assert repaired.severity == "medium"


def test_scratch_defaults_to_low_and_windshield_crack_to_medium():
    scratch, _ = repair_case(
        issue_type="scratch",
        severity="medium",
        raw_decision={"claim_status_justification": "A minor surface scrape is visible."},
    )
    crack, _ = repair_case(
        issue_type="crack",
        object_part="windshield",
        severity="high",
        raw_decision={"claim_status_justification": "A windshield crack is visible."},
    )

    assert scratch.severity == "low"
    assert crack.severity == "medium"


def test_nei_clears_supporting_ids_and_sets_unknown_severity():
    repaired, _ = repair_case(
        claim_status="not_enough_information",
        issue_type="scratch",
        severity="low",
        supporting_image_ids="img_1",
    )

    assert repaired.severity == "unknown"
    assert repaired.supporting_image_ids == "none"


def test_issue_type_none_sets_severity_none():
    repaired, _ = repair_case(issue_type="none", severity="medium")

    assert repaired.severity == "none"


def test_claim_mismatch_visible_alternate_damage_can_become_contradicted():
    repaired, _ = repair_case(
        claim_status="not_enough_information",
        issue_type="scratch",
        object_part="front_bumper",
        severity="low",
        risk_flags=["claim_mismatch"],
        evidence_standard_met=False,
        valid_image=True,
        supporting_image_ids="img_1",
        raw_decision={
            "claim_status_justification": "img_1 shows clear bumper damage but not the claimed mirror damage.",
            "visual_observations": [{"image_id": "img_1", "visible_issues": ["scratch"]}],
        },
    )

    assert repaired.claim_status == "contradicted"
    assert repaired.evidence_standard_met is True
    assert repaired.supporting_image_ids == "img_1"


def test_contradicted_mismatch_marks_evidence_met_and_keeps_ids():
    repaired, _ = repair_case(
        claim_status="contradicted",
        issue_type="scratch",
        object_part="hood",
        risk_flags=["claim_mismatch", "non_original_image"],
        evidence_standard_met=False,
        valid_image=False,
        supporting_image_ids="img_1",
        raw_decision={"claim_status_justification": "img_1 is a stock photo and shows a different damage claim."},
    )

    assert repaired.claim_status == "contradicted"
    assert repaired.evidence_standard_met is True
    assert repaired.supporting_image_ids == "img_1"
    assert "manual_review_required" in repaired.risk_flags


def test_missing_view_remains_not_enough_information():
    repaired, _ = repair_case(
        claim_status="not_enough_information",
        issue_type="unknown",
        risk_flags=["wrong_angle"],
        evidence_standard_met=False,
        valid_image=True,
        supporting_image_ids="img_1",
        raw_decision={"claim_status_justification": "The claimed part is not visible."},
    )

    assert repaired.claim_status == "not_enough_information"
    assert repaired.supporting_image_ids == "none"


def test_possible_manipulation_removed_when_weak_but_stock_image_flags_review():
    weak, _ = repair_case(
        risk_flags=["possible_manipulation"],
        raw_decision={"claim_status_justification": "Lighting differs between the uploaded angles."},
    )
    stock, _ = repair_case(
        risk_flags=["none"],
        raw_decision={"claim_status_justification": "The image has a stock photo watermark."},
    )

    assert "possible_manipulation" not in weak.risk_flags
    assert "non_original_image" in stock.risk_flags
    assert "manual_review_required" in stock.risk_flags


def test_contradicted_rows_keep_ids_but_nei_rows_do_not():
    contradicted, _ = repair_case(
        claim_status="contradicted",
        issue_type="none",
        severity="none",
        supporting_image_ids="none",
        raw_decision={"visual_observations": [{"image_id": "img_1", "visible_issues": []}]},
    )
    nei, _ = repair_case(
        claim_status="not_enough_information",
        issue_type="unknown",
        supporting_image_ids="img_1",
    )

    assert contradicted.supporting_image_ids == "img_1"
    assert nei.supporting_image_ids == "none"


def test_supported_without_visible_evidence_is_repaired_to_not_enough_information():
    repaired, _ = repair_case(
        claim_status="supported",
        issue_type="unknown",
        object_part="headlight",
        risk_flags=["none"],
        evidence_standard_met=True,
        valid_image=True,
        supporting_image_ids="none",
        raw_decision={
            "claim_status_justification": "img_1 does not provide visible evidence of the car or headlight to assess the claimed crack.",
        },
    )

    assert repaired.claim_status == "not_enough_information"
    assert repaired.evidence_standard_met is False
    assert repaired.severity == "unknown"
    assert "damage_not_visible" in repaired.risk_flags
    assert "wrong_angle" in repaired.risk_flags


def test_missing_package_contents_requires_manual_review_when_expected_item_unknown():
    repaired, _ = repair_case(
        claim_object="package",
        claim_status="supported",
        issue_type="missing_part",
        object_part="contents",
        severity="high",
        risk_flags=["none"],
        raw_decision={
            "claim_status_justification": "img_1 shows the box fully opened with only crumpled newspaper and no ordered product or item present inside the package.",
        },
    )

    assert repaired.claim_status == "not_enough_information"
    assert repaired.issue_type == "unknown"
    assert repaired.severity == "unknown"
    assert repaired.valid_image is False
    assert {"cropped_or_obstructed", "damage_not_visible", "manual_review_required"}.issubset(set(repaired.risk_flags))


def test_minor_dent_or_depression_is_low_severity():
    repaired, _ = repair_case(
        claim_object="laptop",
        claim_status="supported",
        issue_type="dent",
        object_part="corner",
        severity="medium",
        raw_decision={"claim_status_justification": "Image 2 shows a small dent/depression in the laptop corner."},
    )

    assert repaired.severity == "low"


def test_minor_trackpad_surface_mark_does_not_support_physical_damage_claim():
    repaired, _ = repair_case(
        claim_object="laptop",
        claim_status="supported",
        issue_type="scratch",
        object_part="trackpad",
        severity="low",
        risk_flags=["user_history_risk"],
        raw_decision={
            "claim_status_justification": "A minor surface mark/scratch is visible within the circled area on the trackpad.",
        },
    )

    assert repaired.claim_status == "contradicted"
    assert repaired.issue_type == "none"
    assert repaired.severity == "none"
    assert "damage_not_visible" in repaired.risk_flags
    assert "manual_review_required" in repaired.risk_flags


def test_wrong_object_language_preserves_mismatch_flags_and_low_severity():
    repaired, _ = repair_case(
        claim_object="package",
        claim_status="contradicted",
        issue_type="unknown",
        object_part="unknown",
        severity="unknown",
        risk_flags=["damage_not_visible", "user_history_risk"],
        raw_decision={
            "claim_status_justification": "img_1 shows cans with nutrition labels rather than the outside shipping box; no crushed box is visible.",
        },
    )

    assert repaired.severity == "low"
    assert "wrong_object" in repaired.risk_flags
    assert "claim_mismatch" in repaired.risk_flags
    assert "manual_review_required" in repaired.risk_flags


def test_instruction_text_on_package_seal_does_not_create_support():
    repaired, _ = repair_case(
        claim_object="package",
        claim_status="supported",
        issue_type="torn_packaging",
        object_part="seal",
        severity="medium",
        risk_flags=["text_instruction_present", "user_history_risk"],
        raw_decision={
            "claim_status_justification": "The visible VOID/TAMPER EVIDENT tape includes approve this Claim text and appears broken.",
        },
    )

    assert repaired.claim_status == "contradicted"
    assert repaired.issue_type == "none"
    assert repaired.severity == "none"
    assert "damage_not_visible" in repaired.risk_flags
    assert "text_instruction_present" in repaired.risk_flags


def test_no_visible_text_in_observation_does_not_mean_damage_not_visible():
    repaired, _ = repair_case(
        claim_status="supported",
        issue_type="dent",
        object_part="rear_bumper",
        severity="high",
        risk_flags=["none"],
        raw_decision={
            "decision": {
                "claim_status": "supported",
                "claim_status_justification": "img_1 shows a rear bumper dent matching the claim.",
                "evidence_standard_met_reason": "The rear bumper is clearly visible with deformation.",
                "visual_observations": [
                    {
                        "image_id": "img_1",
                        "visible_issues": ["dent"],
                        "visible_text_summary": "No visible text or labels in the image.",
                    }
                ],
            }
        },
    )

    assert repaired.claim_status == "supported"
    assert repaired.issue_type == "dent"
    assert repaired.severity == "medium"
    assert repaired.risk_flags == ["none"]


def test_neither_image_has_claimed_damage_marks_claim_mismatch():
    repaired, _ = repair_case(
        claim_status="supported",
        issue_type="unknown",
        object_part="rear_bumper",
        severity="unknown",
        risk_flags=["user_history_risk"],
        evidence_standard_met=True,
        valid_image=True,
        supporting_image_ids="none",
        available_image_ids=["img_1", "img_2"],
        raw_decision={
            "claim_status_justification": "Neither img_1 nor img_2 provides visible evidence of a car or rear bumper damage, so the claim cannot be verified.",
        },
    )

    assert repaired.claim_status == "contradicted"
    assert repaired.evidence_standard_met is True
    assert repaired.severity == "low"
    assert "claim_mismatch" in repaired.risk_flags
    assert "manual_review_required" in repaired.risk_flags
