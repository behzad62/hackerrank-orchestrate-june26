from pathlib import Path

from config import AppConfig
from schemas import (
    ALLOWED_CLAIM_STATUS,
    ALLOWED_ISSUE_TYPES,
    ALLOWED_OBJECT_PARTS,
    ALLOWED_RISK_FLAGS,
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
    assert {"dent", "scratch", "glass_shatter", "unknown"}.issubset(ALLOWED_ISSUE_TYPES)
    assert "text_instruction_present" in ALLOWED_RISK_FLAGS
    assert ALLOWED_OBJECT_PARTS["car"] >= {"front_bumper", "rear_bumper", "unknown"}
    assert ALLOWED_OBJECT_PARTS["laptop"] >= {"screen", "keyboard", "unknown"}
    assert ALLOWED_OBJECT_PARTS["package"] >= {"box", "seal", "unknown"}


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
