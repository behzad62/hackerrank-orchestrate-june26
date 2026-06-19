import json
from datetime import datetime

import pytest

from cache import build_cache_key, read_cache, write_cache
from logging_config import JsonlLogger, redact_value


def test_redact_value_hides_obvious_secrets_and_truncates_long_strings():
    assert redact_value("sk-live-secret") == "[REDACTED]"
    assert redact_value("sk-ant-secret") == "[REDACTED]"
    assert redact_value("Bearer token-value") == "[REDACTED]"
    assert redact_value("provider rejected invalid API key sk-abc123 in request") == "[REDACTED]"
    assert redact_value("debug: authorization failed for sk-ant-abc123 token") == "[REDACTED]"
    long_prose = ("This is ordinary prose, not a base64 payload. " * 8).strip()
    assert redact_value(long_prose) == long_prose[:240] + "..."
    prose_with_spaces = "ordinary prose with spaces " * 20
    assert redact_value(prose_with_spaces) == prose_with_spaces[:240] + "..."


def test_redact_value_hides_generic_image_data_and_base64_payloads():
    assert redact_value("data:image/jpeg;base64," + ("a" * 300)) == "[REDACTED]"
    assert redact_value("data:image;base64," + ("a" * 300)) == "[REDACTED]"
    assert redact_value("A" * 320) == "[REDACTED]"
    assert redact_value("a" * 300) == "[REDACTED]"
    assert redact_value(("A_B-" * 80) + "==") == "[REDACTED]"
    wrapped_payload = "\n".join(["QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="] * 10)
    assert redact_value(wrapped_payload) == "[REDACTED]"


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


def test_jsonl_logger_appends_one_json_object_per_line(tmp_path):
    logger = JsonlLogger(tmp_path / "run.jsonl")
    logger.write("run_started", count=1)
    logger.write("run_completed", count=2)

    records = [
        json.loads(line)
        for line in (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == ["run_started", "run_completed"]
    assert [record["count"] for record in records] == [1, 2]


def test_jsonl_logger_preserves_generated_timestamp_and_event(tmp_path):
    logger = JsonlLogger(tmp_path / "run.jsonl")
    logger.write("safe_event", timestamp="caller timestamp", event="caller event", detail="kept")

    record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8"))
    assert record["event"] == "safe_event"
    assert record["detail"] == "kept"
    assert record["timestamp"] != "caller timestamp"
    datetime.fromisoformat(record["timestamp"])


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


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "../" + ("a" * 64),
        ("a" * 63),
        ("g" * 64),
        ("a" * 64) + "/escape",
    ],
)
def test_cache_rejects_unsafe_keys(tmp_path, unsafe_key):
    with pytest.raises(ValueError):
        read_cache(tmp_path, unsafe_key)
    with pytest.raises(ValueError):
        write_cache(tmp_path, unsafe_key, {"decision": {}})
