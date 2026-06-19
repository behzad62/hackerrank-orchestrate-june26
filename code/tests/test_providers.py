import json
from pathlib import Path

import pytest
import requests

from providers.anthropic import AnthropicProvider
from providers.openai_compatible import OpenAICompatibleProvider, categorize_http_error, extract_json_object
from schemas import PreparedImage, PredictionContext


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text if text is not None else json.dumps(self._payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def sample_context():
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
            "user_claim": "front bumper scratch",
            "claim_object": "car",
        },
        prepared_images=[image],
    )


def test_extract_json_object_from_raw_json():
    assert extract_json_object('{"decision": {"claim_status": "supported"}}')["decision"]["claim_status"] == "supported"


def test_extract_json_object_from_fenced_text():
    wrapped = 'Here is the result:\n```json\n{"decision": {"claim_status": "contradicted"}}\n```'
    assert extract_json_object(wrapped)["decision"]["claim_status"] == "contradicted"


def test_extract_json_object_from_wrapped_text():
    text = 'prefix {"decision": {"claim_status": "supported"}} suffix'
    assert extract_json_object(text)["decision"]["claim_status"] == "supported"


def test_categorize_http_error():
    assert categorize_http_error(401, "bad key") == "auth_error"
    assert categorize_http_error(402, "credits") == "insufficient_credit"
    assert categorize_http_error(429, "slow down") == "rate_limited"
    assert categorize_http_error(408, "request timed out") == "timeout"
    assert categorize_http_error(413, "too large") == "context_length_exceeded"
    assert categorize_http_error(400, "context length exceeded") == "context_length_exceeded"
    assert categorize_http_error(400, "token limit exceeded") == "context_length_exceeded"
    assert categorize_http_error(400, "unsupported image format") == "unsupported_image"
    assert categorize_http_error(400, "invalid image") == "bad_request"
    assert categorize_http_error(529, "overloaded") == "server_error"
    assert categorize_http_error(500, "server") == "server_error"
    assert categorize_http_error(418, "teapot") == "unknown_provider_error"


def test_openai_compatible_packages_image_url(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"decision":{"claim_status":"supported"}}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            headers={"x-request-id": "req_123"},
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    content = captured["json"]["messages"][0]["content"]
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "model"
    assert captured["json"]["temperature"] == 0.0
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert any(part.get("type") == "text" and "front bumper scratch" in part.get("text", "") for part in content)
    assert any(
        part.get("type") == "image_url"
        and part["image_url"]["url"] == "data:image/jpeg;base64,abcd"
        and part["image_url"]["detail"] == "high"
        for part in content
    )
    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.total_tokens == 15
    assert result.metadata.finish_reason == "stop"
    assert result.metadata.request_id == "req_123"


def test_openrouter_headers_are_included(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["headers"] = headers
        return FakeResponse(
            payload={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"decision":{}}'}}],
                "usage": {},
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openrouter",
        api_key="sk-test",
        model="model",
        base_url="https://openrouter.ai/api/v1",
    )
    provider.review_claim(sample_context())

    assert captured["headers"]["HTTP-Referer"] == "https://localhost/hackerrank-orchestrate"
    assert captured["headers"]["X-Title"] == "HackerRank Orchestrate Claim Verification"


def test_openai_compatible_returns_error_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(status_code=429, text="rate limit exceeded")

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.http_status == 429
    assert result.metadata.error_category == "rate_limited"


def test_openai_compatible_returns_timeout_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "timeout"


def test_openai_compatible_returns_network_error_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.exceptions.RequestException("network down")

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "network_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"finish_reason": "stop", "message": {}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
    ],
)
def test_openai_compatible_returns_json_parse_error_for_malformed_payload(monkeypatch, payload):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(payload=payload)

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"


def test_openai_compatible_returns_json_parse_error_for_invalid_response_json(monkeypatch):
    class BadJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("invalid response json")

    def fake_post(url, headers, json, timeout):
        return BadJsonResponse(text="<html>not json</html>")

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"


def test_openai_compatible_marks_length_finish_reason_as_truncated(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"decision":{"claim_status":"supported"}}'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.metadata.finish_reason == "length"
    assert result.metadata.error_category == "response_truncated"


def test_openai_compatible_prioritizes_length_over_incomplete_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"decision":{"claim_status":"supported"'},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
    )
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "response_truncated"
    assert result.metadata.finish_reason == "length"
    assert result.metadata.total_tokens == 15


def test_anthropic_packages_image_blocks(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"decision":{"claim_status":"supported"}}'}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
            },
            headers={"request-id": "req_ant_123"},
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    content = captured["json"]["messages"][0]["content"]
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["model"] == "model"
    assert any(part.get("type") == "text" and "front bumper scratch" in part.get("text", "") for part in content)
    assert any(
        part.get("type") == "image"
        and part["source"] == {"type": "base64", "media_type": "image/jpeg", "data": "abcd"}
        for part in content
    )
    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.total_tokens == 18
    assert result.metadata.finish_reason == "end_turn"
    assert result.metadata.request_id == "req_ant_123"


def test_anthropic_returns_error_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(status_code=402, text="insufficient credits")

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.http_status == 402
    assert result.metadata.error_category == "insufficient_credit"


def test_anthropic_returns_timeout_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "timeout"


def test_anthropic_returns_network_error_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.exceptions.RequestException("network down")

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "network_error"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"content": []},
        {"content": [{"type": "tool_use", "input": {}}]},
        {"content": [{"type": "text", "text": "not json"}]},
    ],
)
def test_anthropic_returns_json_parse_error_for_malformed_payload(monkeypatch, payload):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(payload=payload)

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"


def test_anthropic_returns_json_parse_error_for_invalid_response_json(monkeypatch):
    class BadJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("invalid response json")

    def fake_post(url, headers, json, timeout):
        return BadJsonResponse(text="<html>not json</html>")

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"


def test_anthropic_marks_max_tokens_stop_reason_as_truncated(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": '{"decision":{"claim_status":"supported"}}'}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.metadata.finish_reason == "max_tokens"
    assert result.metadata.error_category == "response_truncated"


def test_anthropic_prioritizes_max_tokens_over_incomplete_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "max_tokens",
                "content": [{"type": "text", "text": '{"decision":{"claim_status":"supported"'}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "response_truncated"
    assert result.metadata.finish_reason == "max_tokens"
    assert result.metadata.total_tokens == 18
