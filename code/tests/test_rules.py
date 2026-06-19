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
