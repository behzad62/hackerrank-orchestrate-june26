from __future__ import annotations

from schemas import PredictionContext, ProviderMetadata, ProviderResult


class FallbackProvider:
    name = "none"
    model = "none"

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        del context
        return ProviderResult(
            raw_json={
                "decision": {
                    "evidence_standard_met": False,
                    "evidence_standard_met_reason": (
                        "No VLM provider was configured, so the submitted images could not be inspected."
                    ),
                    "risk_flags": ["manual_review_required"],
                    "issue_type": "unknown",
                    "object_part": "unknown",
                    "claim_status": "not_enough_information",
                    "claim_status_justification": (
                        "Automated visual review was unavailable; image evidence could not be evaluated."
                    ),
                    "supporting_image_ids": [],
                    "valid_image": False,
                    "severity": "unknown",
                }
            },
            metadata=ProviderMetadata(provider="none", model="none"),
            used_fallback=True,
        )

    def complete_json(self, prompt: str) -> ProviderResult:
        del prompt
        return ProviderResult(
            raw_json={
                "decision": {
                    "evidence_standard_met": False,
                    "evidence_standard_met_reason": (
                        "No text adjudicator provider was configured, so the claim could not be adjudicated."
                    ),
                    "risk_flags": ["manual_review_required"],
                    "issue_type": "unknown",
                    "object_part": "unknown",
                    "claim_status": "not_enough_information",
                    "claim_status_justification": "Automated adjudication was unavailable.",
                    "supporting_image_ids": [],
                    "valid_image": False,
                    "severity": "unknown",
                }
            },
            metadata=ProviderMetadata(provider="none", model="none"),
            used_fallback=True,
        )
