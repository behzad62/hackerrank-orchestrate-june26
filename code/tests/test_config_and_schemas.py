from pathlib import Path

from config import AppConfig
from schemas import (
    ALLOWED_CLAIM_STATUS,
    ALLOWED_ISSUE_TYPES,
    ALLOWED_OBJECT_PARTS,
    ALLOWED_RISK_FLAGS,
    ALLOWED_SEVERITY,
    OUTPUT_COLUMNS,
    AppPaths,
    bool_to_csv,
)


def test_output_columns_match_problem_statement_order():
    assert OUTPUT_COLUMNS == [
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


def test_allowed_values_include_required_enums():
    assert ALLOWED_CLAIM_STATUS == {"supported", "contradicted", "not_enough_information"}
    assert ALLOWED_ISSUE_TYPES == {
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
    assert ALLOWED_RISK_FLAGS == {
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
    assert ALLOWED_OBJECT_PARTS["car"] == {
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
    }
    assert ALLOWED_OBJECT_PARTS["laptop"] == {
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
    }
    assert ALLOWED_OBJECT_PARTS["package"] == {
        "box",
        "package_corner",
        "package_side",
        "seal",
        "label",
        "contents",
        "item",
        "unknown",
    }
    assert ALLOWED_SEVERITY == {"none", "low", "medium", "high", "unknown"}


def test_bool_to_csv_lowercase_strings():
    assert bool_to_csv(True) == "true"
    assert bool_to_csv(False) == "false"


def test_config_defaults_to_honest_none_provider(monkeypatch, tmp_path):
    monkeypatch.delenv("VLM_PROVIDER", raising=False)
    monkeypatch.delenv("ALLOW_NO_VISION_FALLBACK", raising=False)
    cfg = AppConfig.from_env(repo_root=tmp_path)
    assert cfg.provider == "none"
    assert cfg.allow_no_vision_fallback is True
    assert cfg.paths.claims_csv == tmp_path / "dataset" / "claims.csv"
    assert cfg.paths.output_csv == tmp_path / "output.csv"


def test_cli_overrides_env_paths(tmp_path):
    paths = AppPaths.from_repo_root(tmp_path)
    cfg = AppConfig(provider="none", model="", paths=paths)
    updated = cfg.with_overrides(claims=Path("custom.csv"), output=Path("custom_output.csv"))
    assert updated.paths.claims_csv == Path("custom.csv")
    assert updated.paths.output_csv == Path("custom_output.csv")
