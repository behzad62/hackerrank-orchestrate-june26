from pathlib import Path

from config import AppConfig, parse_model_prices
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


def test_config_reads_retry_and_reasoning_generation_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("VLM_RETRY_MAX_SLEEP_SECONDS", "45")
    monkeypatch.setenv("VLM_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setenv("VLM_MAX_CONCURRENCY", "3")
    monkeypatch.setenv("VLM_REQUESTS_PER_MINUTE", "60")
    monkeypatch.setenv("VLM_BACKUP_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("VLM_REASONING_ENABLED", "true")
    monkeypatch.setenv("VLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("VLM_REASONING_MAX_TOKENS", "1200")
    monkeypatch.setenv("VLM_REASONING_EXCLUDE", "true")

    cfg = AppConfig.from_env(repo_root=tmp_path)

    assert cfg.retry_max_sleep_seconds == 45
    assert cfg.max_output_tokens == 4096
    assert cfg.max_concurrency == 3
    assert cfg.requests_per_minute == 60
    assert cfg.backup_max_concurrency == 2
    assert cfg.reasoning_enabled is True
    assert cfg.reasoning_effort == "low"
    assert cfg.reasoning_max_tokens == 1200
    assert cfg.reasoning_exclude is True


def test_config_reads_two_pass_strategy_controls(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIM_REVIEW_STRATEGY_MODE", "two_pass")
    monkeypatch.setenv("ADJUDICATOR_PROVIDER", "openrouter")
    monkeypatch.setenv("ADJUDICATOR_MODEL", "minimax/minimax-m3")

    cfg = AppConfig.from_env(repo_root=tmp_path)

    assert cfg.strategy_mode == "two_pass"
    assert cfg.adjudicator_provider == "openrouter"
    assert cfg.adjudicator_model == "minimax/minimax-m3"


def test_config_with_overrides_accepts_two_pass_strategy_controls(tmp_path):
    cfg = AppConfig(provider="openrouter", model="minimax/minimax-m3", paths=AppPaths.from_repo_root(tmp_path))

    updated = cfg.with_overrides(
        strategy_mode="two_pass",
        adjudicator_provider="openrouter",
        adjudicator_model="minimax/minimax-m3",
    )

    assert updated.strategy_mode == "two_pass"
    assert updated.adjudicator_provider == "openrouter"
    assert updated.adjudicator_model == "minimax/minimax-m3"


def test_config_reads_backup_chain(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOW_BACKUP_VLM", "true")
    monkeypatch.setenv(
        "VLM_BACKUP_CHAIN",
        "openrouter:openai/gpt-4.1-mini,anthropic:claude-3-5-sonnet-latest",
    )

    cfg = AppConfig.from_env(repo_root=tmp_path)

    assert cfg.allow_backup_vlm is True
    assert [(spec.provider, spec.model) for spec in cfg.backup_chain] == [
        ("openrouter", "openai/gpt-4.1-mini"),
        ("anthropic", "claude-3-5-sonnet-latest"),
    ]


def test_parse_model_prices_uses_provider_model_keys():
    prices = parse_model_prices(
        "openrouter:qwen/qwen3.7-plus=0.32,1.28;"
        "gemini:gemini-3.5-flash=1.50,9.00"
    )

    assert prices[("openrouter", "qwen/qwen3.7-plus")] == (0.32, 1.28)
    assert prices[("gemini", "gemini-3.5-flash")] == (1.50, 9.00)


def test_cli_overrides_env_paths(tmp_path):
    paths = AppPaths.from_repo_root(tmp_path)
    cfg = AppConfig(provider="none", model="", paths=paths)
    updated = cfg.with_overrides(claims=Path("custom.csv"), output=Path("custom_output.csv"))
    assert updated.paths.claims_csv == Path("custom.csv")
    assert updated.paths.output_csv == Path("custom_output.csv")
