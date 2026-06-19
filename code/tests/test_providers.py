import json
from pathlib import Path

import pytest
import requests

from providers.anthropic import AnthropicProvider
from providers.gemini import GeminiProvider, categorize_gemini_http_error
from providers.openai_compatible import OpenAICompatibleProvider, categorize_http_error, extract_json_object
from schemas import PreparedImage, PredictionContext


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
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
    assert categorize_http_error(403, "quota exhausted") == "insufficient_credit"
    assert categorize_http_error(403, "invalid API key") == "auth_error"
    assert categorize_http_error(402, "credits") == "insufficient_credit"
    assert categorize_http_error(429, "slow down") == "rate_limited"
    assert categorize_http_error(408, "request timed out") == "timeout"
    assert categorize_http_error(413, "too large") == "context_length_exceeded"
    assert categorize_http_error(400, "context length exceeded") == "context_length_exceeded"
    assert categorize_http_error(400, "token limit exceeded") == "context_length_exceeded"
    assert categorize_http_error(400, "unsupported image format") == "unsupported_image"
    assert categorize_http_error(404, "No endpoints found that support image input") == "unsupported_image"
    assert categorize_http_error(400, "This model does not support images") == "unsupported_image"
    assert categorize_http_error(400, "Unsupported modality: image_url") == "unsupported_image"
    assert categorize_http_error(400, "invalid image") == "bad_request"
    assert categorize_http_error(529, "overloaded") == "server_error"
    assert categorize_http_error(500, "server") == "server_error"
    assert categorize_http_error(418, "teapot") == "unknown_provider_error"


def test_categorize_gemini_http_error():
    assert categorize_gemini_http_error(403, "PERMISSION_DENIED") == "auth_error"
    assert categorize_gemini_http_error(429, "RESOURCE_EXHAUSTED") == "rate_limited"
    assert categorize_gemini_http_error(400, "Request payload size exceeds the limit") == "context_length_exceeded"
    assert categorize_gemini_http_error(400, "INVALID_ARGUMENT") == "bad_request"
    assert categorize_gemini_http_error(500, "INTERNAL") == "server_error"


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

    messages = captured["json"]["messages"]
    system_content = messages[0]["content"]
    user_content = messages[1]["content"]
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "model"
    assert captured["json"]["temperature"] == 0.0
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert messages[0]["role"] == "system"
    assert "front bumper scratch" not in system_content[0]["text"]
    assert any(part.get("type") == "text" and "front bumper scratch" in part.get("text", "") for part in user_content)
    assert any(
        part.get("type") == "image_url"
        and part["image_url"]["url"] == "data:image/jpeg;base64,abcd"
        and part["image_url"]["detail"] == "high"
        for part in user_content
    )
    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.total_tokens == 15
    assert result.metadata.finish_reason == "stop"
    assert result.metadata.request_id == "req_123"


def test_openai_compatible_parses_prompt_cache_usage(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"decision":{"claim_status":"supported"}}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "total_tokens": 105,
                    "prompt_tokens_details": {"cached_tokens": 64},
                },
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model="model",
        base_url="https://api.openai.com/v1",
        prompt_cache_enabled=True,
        prompt_cache_retention="24h",
    )
    result = provider.review_claim(sample_context())

    assert result.metadata.cached_tokens == 64
    assert result.metadata.cache_hit_ratio == 0.64
    assert result.metadata.prompt_cache_retention == "24h"
    assert result.metadata.prompt_cache_key_used is True


def test_openrouter_headers_are_included(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["headers"] = headers
        captured["json"] = json
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
    assert captured["headers"]["X-OpenRouter-Title"] == "HackerRank Orchestrate Claim Verification"
    assert captured["json"]["max_completion_tokens"] == 1800
    assert "max_tokens" not in captured["json"]


def test_openrouter_uses_system_cache_breakpoint_and_dynamic_user_content(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(
            payload={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"decision":{}}'}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                    "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 20},
                },
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openrouter",
        api_key="sk-test",
        model="qwen/qwen3.7-plus",
        base_url="https://openrouter.ai/api/v1",
        prompt_cache_enabled=True,
    )
    result = provider.review_claim(sample_context())

    messages = captured["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"][0]["type"] == "text"
    assert messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "front bumper scratch" not in messages[0]["content"][0]["text"]
    assert messages[1]["role"] == "user"
    assert any(part.get("type") == "text" and "front bumper scratch" in part.get("text", "") for part in messages[1]["content"])
    assert captured["json"]["session_id"] == "hackerrank-orchestrate-claim-review-v1"
    assert result.metadata.cached_tokens == 80
    assert result.metadata.cache_creation_input_tokens == 20
    assert result.metadata.cache_read_input_tokens == 80


def test_openrouter_omits_cache_controls_when_prompt_cache_disabled(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
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
        model="qwen/qwen3.7-plus",
        base_url="https://openrouter.ai/api/v1",
        prompt_cache_enabled=False,
    )
    provider.review_claim(sample_context())

    assert "cache_control" not in captured["json"]["messages"][0]["content"][0]
    assert "session_id" not in captured["json"]


@pytest.mark.parametrize("model", ["o3-mini", "gpt-5"])
def test_openai_reasoning_models_use_max_completion_tokens(monkeypatch, model):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(
            payload={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"decision":{}}'}}],
                "usage": {},
            }
        )

    monkeypatch.setattr("providers.openai_compatible.requests.post", fake_post)
    provider = OpenAICompatibleProvider(
        provider="openai",
        api_key="sk-test",
        model=model,
        base_url="https://api.openai.com/v1",
        max_output_tokens=1200,
    )
    provider.review_claim(sample_context())

    assert captured["json"]["max_completion_tokens"] == 1200
    assert "max_tokens" not in captured["json"]


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
        [],
        "not an object",
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


def test_openai_compatible_preserves_metadata_for_parse_invalid_model_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "not json"},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            headers={"x-request-id": "req_parse"},
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
    assert result.metadata.error_category == "json_parse_error"
    assert result.metadata.finish_reason == "stop"
    assert result.metadata.prompt_tokens == 10
    assert result.metadata.completion_tokens == 5
    assert result.metadata.total_tokens == 15


def test_openai_compatible_defaults_malformed_usage_for_parse_error(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "not json"},
                    }
                ],
                "usage": {"prompt_tokens": "bad", "completion_tokens": [], "total_tokens": {}},
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
    assert result.metadata.error_category == "json_parse_error"
    assert result.metadata.finish_reason == "stop"
    assert result.metadata.prompt_tokens == 0
    assert result.metadata.completion_tokens == 0
    assert result.metadata.total_tokens == 0


def test_openai_compatible_defaults_malformed_usage_for_success(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"decision":{"claim_status":"supported"}}'},
                    }
                ],
                "usage": {"prompt_tokens": "bad", "completion_tokens": [], "total_tokens": {}},
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

    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.prompt_tokens == 0
    assert result.metadata.completion_tokens == 0
    assert result.metadata.total_tokens == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
    ],
)
def test_openai_compatible_preserves_usage_for_malformed_choices(monkeypatch, payload):
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
    assert result.metadata.prompt_tokens == 7
    assert result.metadata.completion_tokens == 3
    assert result.metadata.total_tokens == 10


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


def test_anthropic_uses_static_prefix_cache_control_and_parses_usage(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"decision":{"claim_status":"supported"}}'}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 8,
                    "cache_creation_input_tokens": 32,
                    "cache_read_input_tokens": 48,
                },
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="model",
        prompt_cache_enabled=True,
        prompt_cache_retention="1h",
    )
    result = provider.review_claim(sample_context())

    system = captured["json"]["system"]
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "front bumper scratch" not in system[0]["text"]
    assert result.metadata.cache_creation_input_tokens == 32
    assert result.metadata.cache_read_input_tokens == 48
    assert result.metadata.cached_tokens == 48
    assert result.metadata.cache_hit_ratio == 0.48
    assert result.metadata.prompt_cache_retention == "1h"
    assert result.metadata.prompt_cache_key_used is True


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
        [],
        "not an object",
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


def test_anthropic_preserves_metadata_for_parse_invalid_model_json(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "not json"}],
                "usage": {"input_tokens": 12, "output_tokens": 6},
            },
            headers={"request-id": "req_ant_parse"},
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"
    assert result.metadata.finish_reason == "end_turn"
    assert result.metadata.prompt_tokens == 12
    assert result.metadata.completion_tokens == 6
    assert result.metadata.total_tokens == 18


def test_anthropic_defaults_malformed_usage_for_parse_error(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "not json"}],
                "usage": {"input_tokens": "bad", "output_tokens": []},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"
    assert result.metadata.finish_reason == "end_turn"
    assert result.metadata.prompt_tokens == 0
    assert result.metadata.completion_tokens == 0
    assert result.metadata.total_tokens == 0


def test_anthropic_defaults_malformed_usage_for_success(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"decision":{"claim_status":"supported"}}'}],
                "usage": {"input_tokens": "bad", "output_tokens": []},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.prompt_tokens == 0
    assert result.metadata.completion_tokens == 0
    assert result.metadata.total_tokens == 0


@pytest.mark.parametrize("content", [[], [{"type": "tool_use", "input": {}}]])
def test_anthropic_preserves_metadata_for_malformed_content(monkeypatch, content):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "end_turn",
                "content": content,
                "usage": {"input_tokens": 12, "output_tokens": 6},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "json_parse_error"
    assert result.metadata.finish_reason == "end_turn"
    assert result.metadata.prompt_tokens == 12
    assert result.metadata.completion_tokens == 6
    assert result.metadata.total_tokens == 18


@pytest.mark.parametrize("content", [[], [{"type": "tool_use", "input": {}}]])
def test_anthropic_prioritizes_max_tokens_for_malformed_content(monkeypatch, content):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "stop_reason": "max_tokens",
                "content": content,
                "usage": {"input_tokens": 12, "output_tokens": 6},
            }
        )

    monkeypatch.setattr("providers.anthropic.requests.post", fake_post)
    provider = AnthropicProvider(api_key="sk-ant-test", model="model")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.error_category == "response_truncated"
    assert result.metadata.finish_reason == "max_tokens"
    assert result.metadata.prompt_tokens == 12
    assert result.metadata.completion_tokens == 6
    assert result.metadata.total_tokens == 18


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


def test_gemini_packages_inline_images_and_static_system_instruction(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            payload={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"decision":{"claim_status":"supported"}}'}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 90,
                    "candidatesTokenCount": 11,
                    "totalTokenCount": 101,
                    "cachedContentTokenCount": 45,
                },
            },
            headers={"x-request-id": "gem_req_1"},
        )

    monkeypatch.setattr("providers.gemini.requests.post", fake_post)
    provider = GeminiProvider(api_key="gemini-test", model="gemini-3.5-flash", max_output_tokens=1800)
    result = provider.review_claim(sample_context())

    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"
    assert captured["headers"]["x-goog-api-key"] == "gemini-test"
    assert captured["json"]["systemInstruction"]["parts"][0]["text"]
    assert "front bumper scratch" not in captured["json"]["systemInstruction"]["parts"][0]["text"]
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Allowed object_part for this row:")
    assert any(part.get("inline_data") == {"mime_type": "image/jpeg", "data": "abcd"} for part in parts)
    assert captured["json"]["generationConfig"] == {
        "maxOutputTokens": 1800,
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "medium"},
    }
    assert result.raw_json["decision"]["claim_status"] == "supported"
    assert result.metadata.prompt_tokens == 90
    assert result.metadata.completion_tokens == 11
    assert result.metadata.cached_tokens == 45
    assert result.metadata.cache_hit_ratio == 0.5
    assert result.metadata.prompt_cache_key_used is True


def test_gemini_marks_max_tokens_as_truncated(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(
            payload={
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": '{"decision":{"claim_status":"supported"}}'}]},
                    }
                ],
                "usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 1, "totalTokenCount": 91},
            }
        )

    monkeypatch.setattr("providers.gemini.requests.post", fake_post)
    provider = GeminiProvider(api_key="gemini-test", model="gemini-3.5-flash")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.finish_reason == "MAX_TOKENS"
    assert result.metadata.error_category == "response_truncated"


def test_gemini_returns_error_metadata(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return FakeResponse(status_code=429, text='{"error":{"status":"RESOURCE_EXHAUSTED"}}')

    monkeypatch.setattr("providers.gemini.requests.post", fake_post)
    provider = GeminiProvider(api_key="gemini-test", model="gemini-3.5-flash")
    result = provider.review_claim(sample_context())

    assert result.raw_json == {"decision": {}}
    assert result.metadata.http_status == 429
    assert result.metadata.error_category == "rate_limited"
