from __future__ import annotations

from normalization import normalize_provider_result
from schemas import PredictionContext, ProviderMetadata, ProviderResult


def test_user_history_risk_is_owned_by_user_history_not_provider_output():
    context = PredictionContext(
        row_index=1,
        row={
            "user_id": "u1",
            "image_paths": "images/sample/case_001/img_1.jpg",
            "user_claim": "The package contents are missing.",
            "claim_object": "package",
        },
        user_history={"history_flags": "manual_review_required"},
    )
    result = ProviderResult(
        raw_json={
            "decision": {
                "evidence_standard_met": False,
                "evidence_standard_met_reason": "The open box does not show enough of the contents.",
                "risk_flags": ["damage_not_visible", "user_history_risk"],
                "issue_type": "unknown",
                "object_part": "contents",
                "claim_status": "not_enough_information",
                "claim_status_justification": "img_1 cannot verify whether the ordered item is missing.",
                "supporting_image_ids": [],
                "valid_image": False,
                "severity": "unknown",
            }
        },
        metadata=ProviderMetadata(provider="openrouter", model="test-model"),
    )

    row, _ = normalize_provider_result(context, result)

    assert "user_history_risk" not in row["risk_flags"].split(";")
    assert row["risk_flags"] == "cropped_or_obstructed;damage_not_visible;manual_review_required"


def test_normalization_passes_claim_context_to_rule_calibration():
    context = PredictionContext(
        row_index=1,
        row={
            "user_id": "u1",
            "image_paths": "images/sample/case_001/img_1.jpg",
            "user_claim": "The back of the car has a dent now. Mostly the rear bumper area.",
            "claim_object": "car",
        },
    )
    result = ProviderResult(
        raw_json={
            "decision": {
                "evidence_standard_met": True,
                "evidence_standard_met_reason": "The rear of the vehicle is visible.",
                "risk_flags": ["none"],
                "issue_type": "broken_part",
                "object_part": "rear_bumper",
                "claim_status": "supported",
                "claim_status_justification": (
                    "Image img_1 shows severe damage to the rear of the vehicle, where the rear bumper "
                    "cover is missing and the bumper structure is crushed and deformed."
                ),
                "supporting_image_ids": ["img_1"],
                "valid_image": True,
                "severity": "high",
            },
            "visual_observations": [
                {
                    "image_id": "img_1",
                    "visible_issues": ["broken_part", "dent", "missing_part"],
                    "visible_parts": ["rear_bumper", "body", "taillight"],
                }
            ],
        },
        metadata=ProviderMetadata(provider="openrouter", model="test-model"),
    )

    row, _ = normalize_provider_result(context, result)

    assert row["issue_type"] == "dent"
    assert row["severity"] == "medium"
