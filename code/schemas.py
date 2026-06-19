from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUTPUT_COLUMNS = [
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]

ALLOWED_CLAIM_OBJECTS = {"car", "laptop", "package"}
ALLOWED_CLAIM_STATUS = {"supported", "contradicted", "not_enough_information"}
ALLOWED_ISSUE_TYPES = {
    "dent",
    "scratch",
    "crack",
    "glass_shatter",
    "broken_part",
    "missing_part",
    "torn_packaging",
    "crushed_packaging",
    "water_damage",
    "stain",
    "none",
    "unknown",
}
ALLOWED_OBJECT_PARTS = {
    "car": {
        "front_bumper",
        "rear_bumper",
        "door",
        "hood",
        "windshield",
        "side_mirror",
        "headlight",
        "taillight",
        "fender",
        "quarter_panel",
        "body",
        "unknown",
    },
    "laptop": {
        "screen",
        "keyboard",
        "trackpad",
        "hinge",
        "lid",
        "corner",
        "port",
        "base",
        "body",
        "unknown",
    },
    "package": {
        "box",
        "package_corner",
        "package_side",
        "seal",
        "label",
        "contents",
        "item",
        "unknown",
    },
}
ALLOWED_RISK_FLAGS = {
    "none",
    "blurry_image",
    "cropped_or_obstructed",
    "low_light_or_glare",
    "wrong_angle",
    "wrong_object",
    "wrong_object_part",
    "damage_not_visible",
    "claim_mismatch",
    "possible_manipulation",
    "non_original_image",
    "text_instruction_present",
    "user_history_risk",
    "manual_review_required",
}
ALLOWED_SEVERITY = {"none", "low", "medium", "high", "unknown"}


def bool_to_csv(value: bool) -> str:
    return "true" if bool(value) else "false"


def split_semicolon(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


@dataclass(frozen=True)
class AppPaths:
    repo_root: Path
    claims_csv: Path
    sample_claims_csv: Path
    user_history_csv: Path
    evidence_requirements_csv: Path
    images_dir: Path
    output_csv: Path
    logs_dir: Path
    cache_dir: Path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "AppPaths":
        root = repo_root.resolve()
        return cls(
            repo_root=root,
            claims_csv=root / "dataset" / "claims.csv",
            sample_claims_csv=root / "dataset" / "sample_claims.csv",
            user_history_csv=root / "dataset" / "user_history.csv",
            evidence_requirements_csv=root / "dataset" / "evidence_requirements.csv",
            images_dir=root / "dataset" / "images",
            output_csv=root / "output.csv",
            logs_dir=root / "logs",
            cache_dir=root / ".cache" / "vlm",
        )


@dataclass(frozen=True)
class PreparedImage:
    image_id: str
    original_path: str
    absolute_path: Path
    mime_type: str
    size_bytes: int
    sha256: str
    data_base64: str
    readable: bool = True
    error: str = ""


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    request_id: str = ""
    http_status: int = 0
    error_category: str = ""
    cache_hit: bool = False
    cached_tokens: int = 0
    cache_hit_ratio: float = 0.0
    prompt_cache_retention: str = ""
    prompt_cache_key_used: bool = False
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True)
class ProviderResult:
    raw_json: dict[str, Any]
    metadata: ProviderMetadata
    used_fallback: bool = False


@dataclass
class PredictionContext:
    row_index: int
    row: dict[str, str]
    user_history: dict[str, str] = field(default_factory=dict)
    evidence_requirements: list[dict[str, str]] = field(default_factory=list)
    all_evidence_requirements: list[dict[str, str]] = field(default_factory=list)
    prepared_images: list[PreparedImage] = field(default_factory=list)
    claim_text_risk_flags: list[str] = field(default_factory=list)
