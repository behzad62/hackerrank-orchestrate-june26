from pathlib import Path

from schemas import PreparedImage, PredictionContext
from schemas import ProviderMetadata, ProviderResult
from two_pass import (
    build_adjudicator_prompt,
    build_candidate_decision_from_visual_facts,
    build_visual_fact_prompt_parts,
    run_two_pass_review,
    visual_fact_json_contract,
)


def _context(claim: str = "front bumper scratch", claim_object: str = "car") -> PredictionContext:
    image = PreparedImage(
        image_id="img_1",
        original_path="images/test/case_001/img_1.jpg",
        absolute_path=Path(__file__),
        mime_type="image/jpeg",
        size_bytes=4,
        sha256="a" * 64,
        data_base64="abcd",
    )
    return PredictionContext(
        row_index=1,
        row={
            "user_id": "u1",
            "image_paths": image.original_path,
            "user_claim": claim,
            "claim_object": claim_object,
        },
        user_history={"past_claim_count": "2"},
        evidence_requirements=[{"requirement_id": "REQ_CAR", "minimum_image_evidence": "front bumper visible"}],
        prepared_images=[image],
    )


def test_visual_fact_contract_avoids_final_decision_fields():
    contract = visual_fact_json_contract()

    assert "claim_intent" in contract
    assert "image_observations" in contract
    assert "overall_visual_facts" in contract
    assert "instruction_like_text_visible" in contract
    assert '"claim_status"' not in contract
    assert '"risk_flags"' not in contract
    assert '"severity"' not in contract


def test_visual_fact_prompt_forbids_final_output_decisions():
    parts = build_visual_fact_prompt_parts(_context())

    assert "Do not choose final output.csv values" in parts.static_prefix
    assert "Do not decide final claim_status" in parts.static_prefix
    assert "front bumper scratch" not in parts.static_prefix
    assert "front bumper scratch" in parts.dynamic_suffix
    assert "data_base64" not in parts.full_text


def test_candidate_decision_supports_visible_matching_damage():
    facts = {
        "image_observations": [
            {
                "image_id": "img_1",
                "usable_for_review": True,
                "visible_object_type": "car",
                "visible_parts": ["front_bumper"],
                "visible_damage": ["scratch on front bumper"],
                "claimed_damage_visible": True,
                "relevant_part_visible": True,
            }
        ],
        "overall_visual_facts": {
            "relevant_object_visible": True,
            "relevant_part_visible": True,
            "claimed_damage_visible": True,
            "visible_mismatch": False,
        },
    }

    decision = build_candidate_decision_from_visual_facts(_context(), facts)["decision"]

    assert decision["claim_status"] == "supported"
    assert decision["issue_type"] == "scratch"
    assert decision["object_part"] == "front_bumper"
    assert decision["supporting_image_ids"] == ["img_1"]
    assert decision["evidence_standard_met"] is True


def test_candidate_decision_contradicts_when_relevant_part_visible_without_damage():
    facts = {
        "image_observations": [
            {
                "image_id": "img_1",
                "usable_for_review": True,
                "visible_object_type": "car",
                "visible_parts": ["front_bumper"],
                "visible_damage": [],
                "claimed_damage_visible": False,
                "relevant_part_visible": True,
            }
        ],
        "overall_visual_facts": {
            "relevant_object_visible": True,
            "relevant_part_visible": True,
            "claimed_damage_visible": False,
            "visible_mismatch": False,
        },
    }

    decision = build_candidate_decision_from_visual_facts(_context(), facts)["decision"]

    assert decision["claim_status"] == "contradicted"
    assert decision["issue_type"] == "none"
    assert "damage_not_visible" in decision["risk_flags"]


def test_candidate_decision_nei_when_image_not_usable():
    facts = {
        "image_observations": [
            {
                "image_id": "img_1",
                "usable_for_review": False,
                "visible_object_type": "unknown",
                "visible_parts": [],
                "visible_damage": [],
                "claimed_damage_visible": False,
                "relevant_part_visible": False,
                "quality_issues": ["blurry_image"],
            }
        ],
        "overall_visual_facts": {
            "relevant_object_visible": False,
            "relevant_part_visible": False,
            "claimed_damage_visible": False,
            "visible_mismatch": False,
        },
    }

    decision = build_candidate_decision_from_visual_facts(_context(), facts)["decision"]

    assert decision["claim_status"] == "not_enough_information"
    assert decision["issue_type"] == "unknown"
    assert decision["supporting_image_ids"] == []
    assert "blurry_image" in decision["risk_flags"]


def test_adjudicator_prompt_includes_visual_facts_candidate_and_final_contract():
    facts = {"overall_visual_facts": {"claimed_damage_visible": True}}
    candidate = {"decision": {"claim_status": "supported", "issue_type": "scratch"}}

    prompt = build_adjudicator_prompt(_context(), facts, candidate)

    assert "Final text-only adjudication" in prompt
    assert "visual_facts" in prompt
    assert "candidate_decision" in prompt
    assert "Return JSON only" in prompt
    assert "claim_status" in prompt
    assert "supported" in prompt
    assert "front bumper scratch" in prompt


def test_two_pass_retries_retryable_adjudicator_json_parse_error():
    class VisualProvider:
        name = "openrouter"
        model = "vision-model"

        def review_claim(self, context):
            return ProviderResult(
                raw_json={
                    "decision": {
                        "evidence_standard_met": True,
                        "evidence_standard_met_reason": "The front bumper is visible.",
                        "risk_flags": ["none"],
                        "issue_type": "scratch",
                        "object_part": "front_bumper",
                        "claim_status": "supported",
                        "claim_status_justification": "img_1 shows a scratch on the front bumper.",
                        "supporting_image_ids": ["img_1"],
                        "valid_image": True,
                        "severity": "low",
                    },
                },
                metadata=ProviderMetadata(provider="openrouter", model="vision-model"),
            )

    class AdjudicatorProvider:
        name = "openrouter"
        model = "adjudicator-model"

        def __init__(self):
            self.calls = 0

        def complete_json(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return ProviderResult(
                    raw_json={"decision": {}},
                    metadata=ProviderMetadata(
                        provider="openrouter",
                        model="adjudicator-model",
                        error_category="json_parse_error",
                    ),
                )
            return ProviderResult(
                raw_json={"decision": {"claim_status": "supported"}},
                metadata=ProviderMetadata(provider="openrouter", model="adjudicator-model"),
            )

    adjudicator = AdjudicatorProvider()

    result = run_two_pass_review(
        context=_context(),
        visual_provider=VisualProvider(),
        adjudicator_provider=adjudicator,
        max_retries=1,
    )

    assert adjudicator.calls == 2
    assert result.metadata.error_category == ""
    assert result.raw_json["decision"]["claim_status"] == "supported"
