import json

from cache import build_cache_key, read_cache, write_cache
from logging_config import JsonlLogger, redact_value


def test_redact_value_hides_obvious_secrets_and_truncates_long_strings():
    assert redact_value("sk-live-secret") == "[REDACTED]"
    assert redact_value("sk-ant-secret") == "[REDACTED]"
    assert redact_value("Bearer token-value") == "[REDACTED]"
    assert redact_value("a" * 300) == ("a" * 240) + "..."


def test_jsonl_logger_writes_safe_events(tmp_path):
    logger = JsonlLogger(tmp_path / "run.jsonl")
    logger.write(
        "provider_response",
        provider="none",
        api_key="sk-hidden",
        headers={"Authorization": "Bearer hidden"},
        nested={"session_token": "secret-token"},
        image_payload="data:image/jpeg;base64," + ("a" * 300),
        count=1,
    )

    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8"))
    assert record["event"] == "provider_response"
    assert "timestamp" in record
    assert record["api_key"] == "[REDACTED]"
    assert record["headers"]["Authorization"] == "[REDACTED]"
    assert record["nested"]["session_token"] == "[REDACTED]"
    assert record["image_payload"] == "[REDACTED]"
    assert "base64," not in json.dumps(record)


def test_cache_key_is_deterministic_for_equivalent_structures():
    first = build_cache_key(
        provider="none",
        model="none",
        prompt_version="v1",
        row={"user_claim": "claim", "user_id": "u1"},
        user_history={"history_flags": "none", "past_claim_count": "0"},
        evidence_requirements=[{"requirement_id": "REQ", "claim_object": "car"}],
        image_hashes=["abc", "def"],
        normalizer_version="v1",
    )
    second = build_cache_key(
        provider="none",
        model="none",
        prompt_version="v1",
        row={"user_id": "u1", "user_claim": "claim"},
        user_history={"past_claim_count": "0", "history_flags": "none"},
        evidence_requirements=[{"claim_object": "car", "requirement_id": "REQ"}],
        image_hashes=["abc", "def"],
        normalizer_version="v1",
    )
    changed = build_cache_key(
        provider="none",
        model="none",
        prompt_version="v2",
        row={"user_id": "u1", "user_claim": "claim"},
        user_history={"past_claim_count": "0", "history_flags": "none"},
        evidence_requirements=[{"claim_object": "car", "requirement_id": "REQ"}],
        image_hashes=["abc", "def"],
        normalizer_version="v1",
    )

    assert first == second
    assert first != changed
    assert len(first) == 64


def test_cache_round_trip(tmp_path):
    key = build_cache_key(
        provider="none",
        model="none",
        prompt_version="v1",
        row={"user_id": "u1", "user_claim": "claim"},
        user_history={"history_flags": "none"},
        evidence_requirements=[{"requirement_id": "REQ"}],
        image_hashes=["abc"],
        normalizer_version="v1",
    )

    assert read_cache(tmp_path, key) is None
    write_cache(tmp_path, key, {"decision": {"claim_status": "not_enough_information"}})

    assert read_cache(tmp_path, key)["decision"]["claim_status"] == "not_enough_information"
