from __future__ import annotations

import time
from typing import Any

import requests

from providers.openai_compatible import (
    _cache_hit_ratio,
    _safe_token_count,
    categorize_http_error,
    extract_json_object,
    has_decision_payload,
    has_supported_json_payload,
)
from prompting import build_prompt_parts
from schemas import PredictionContext, ProviderMetadata, ProviderResult


def _normalize_anthropic_usage(usage: Any) -> tuple[int, int, int, int]:
    if not isinstance(usage, dict):
        usage = {}
    return (
        _safe_token_count(usage.get("input_tokens")),
        _safe_token_count(usage.get("output_tokens")),
        _safe_token_count(usage.get("cache_creation_input_tokens")),
        _safe_token_count(usage.get("cache_read_input_tokens")),
    )


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        timeout_seconds: int = 90,
        max_output_tokens: int = 1800,
        prompt_cache_enabled: bool = True,
        prompt_cache_retention: str = "24h",
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.prompt_cache_enabled = prompt_cache_enabled
        self.prompt_cache_retention = prompt_cache_retention

    def _system(self, context: PredictionContext) -> list[dict[str, Any]]:
        block: dict[str, Any] = {
            "type": "text",
            "text": build_prompt_parts(context).static_prefix,
        }
        if self.prompt_cache_enabled:
            cache_control = {"type": "ephemeral"}
            if self.prompt_cache_retention in {"5m", "1h"}:
                cache_control["ttl"] = self.prompt_cache_retention
            block["cache_control"] = cache_control
        return [block]

    def _content(self, context: PredictionContext) -> list[dict[str, Any]]:
        prompt_parts = build_prompt_parts(context)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt_parts.dynamic_suffix}]
        for image in context.prepared_images:
            if not image.readable or not image.data_base64:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime_type,
                        "data": image.data_base64,
                    },
                }
            )
        return content

    def _error_result(
        self,
        *,
        category: str,
        latency_ms: int,
        http_status: int = 0,
        finish_reason: str = "",
        request_id: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> ProviderResult:
        return ProviderResult(
            raw_json={"decision": {}},
            metadata=ProviderMetadata(
                provider=self.name,
                model=self.model,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                request_id=request_id,
                http_status=http_status,
                error_category=category,
                cached_tokens=cache_read_input_tokens,
                cache_hit_ratio=_cache_hit_ratio(cache_read_input_tokens, prompt_tokens),
                prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
                prompt_cache_key_used=self.prompt_cache_enabled,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            ),
        )

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        started = time.monotonic()
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_output_tokens,
                    "temperature": self.temperature,
                    "system": self._system(context),
                    "messages": [{"role": "user", "content": self._content(context)}],
                },
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="timeout", latency_ms=duration_ms)
        except requests.exceptions.RequestException:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="network_error", latency_ms=duration_ms)

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return self._error_result(
                category=categorize_http_error(response.status_code, response.text),
                latency_ms=duration_ms,
                http_status=response.status_code,
                request_id=response.headers.get("request-id", ""),
            )

        input_tokens = 0
        output_tokens = 0
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0
        stop_reason = ""
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response JSON is not an object")
            (
                input_tokens,
                output_tokens,
                cache_creation_input_tokens,
                cache_read_input_tokens,
            ) = _normalize_anthropic_usage(data.get("usage"))
            stop_reason = str(data.get("stop_reason") or "")
            if stop_reason == "max_tokens":
                return self._error_result(
                    category="response_truncated",
                    latency_ms=duration_ms,
                    http_status=response.status_code,
                    finish_reason=stop_reason,
                    request_id=response.headers.get("request-id", ""),
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cache_creation_input_tokens=cache_creation_input_tokens,
                    cache_read_input_tokens=cache_read_input_tokens,
                )
            content = data.get("content")
            if not isinstance(content, list) or not content:
                raise ValueError("missing content")
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
            ]
            if not text_parts:
                raise ValueError("missing text content")
            parsed = extract_json_object("\n".join(text_parts))
            if not has_supported_json_payload(parsed):
                raise ValueError("missing supported payload")
        except (ValueError, TypeError):
            return self._error_result(
                category="json_parse_error",
                latency_ms=duration_ms,
                http_status=response.status_code,
                finish_reason=stop_reason,
                request_id=response.headers.get("request-id", ""),
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            )
        return ProviderResult(
            raw_json=parsed,
            metadata=ProviderMetadata(
                provider=self.name,
                model=self.model,
                latency_ms=duration_ms,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                finish_reason=stop_reason,
                request_id=response.headers.get("request-id", ""),
                http_status=response.status_code,
                error_category="response_truncated" if stop_reason == "max_tokens" else "",
                cached_tokens=cache_read_input_tokens,
                cache_hit_ratio=_cache_hit_ratio(cache_read_input_tokens, input_tokens),
                prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
                prompt_cache_key_used=self.prompt_cache_enabled,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            ),
        )

    def complete_json(self, prompt: str) -> ProviderResult:
        started = time.monotonic()
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_output_tokens,
                    "temperature": self.temperature,
                    "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                },
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="timeout", latency_ms=duration_ms)
        except requests.exceptions.RequestException:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="network_error", latency_ms=duration_ms)

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return self._error_result(
                category=categorize_http_error(response.status_code, response.text),
                latency_ms=duration_ms,
                http_status=response.status_code,
                request_id=response.headers.get("request-id", ""),
            )

        input_tokens = 0
        output_tokens = 0
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0
        stop_reason = ""
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response JSON is not an object")
            (
                input_tokens,
                output_tokens,
                cache_creation_input_tokens,
                cache_read_input_tokens,
            ) = _normalize_anthropic_usage(data.get("usage"))
            stop_reason = str(data.get("stop_reason") or "")
            if stop_reason == "max_tokens":
                return self._error_result(
                    category="response_truncated",
                    latency_ms=duration_ms,
                    http_status=response.status_code,
                    finish_reason=stop_reason,
                    request_id=response.headers.get("request-id", ""),
                    prompt_tokens=input_tokens,
                    completion_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cache_creation_input_tokens=cache_creation_input_tokens,
                    cache_read_input_tokens=cache_read_input_tokens,
                )
            content = data.get("content")
            if not isinstance(content, list) or not content:
                raise ValueError("missing content")
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
            ]
            if not text_parts:
                raise ValueError("missing text content")
            parsed = extract_json_object("\n".join(text_parts))
            if not has_decision_payload(parsed):
                raise ValueError("missing decision payload")
        except (ValueError, TypeError):
            return self._error_result(
                category="json_parse_error",
                latency_ms=duration_ms,
                http_status=response.status_code,
                finish_reason=stop_reason,
                request_id=response.headers.get("request-id", ""),
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            )
        return ProviderResult(
            raw_json=parsed,
            metadata=ProviderMetadata(
                provider=self.name,
                model=self.model,
                latency_ms=duration_ms,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                finish_reason=stop_reason,
                request_id=response.headers.get("request-id", ""),
                http_status=response.status_code,
                error_category="response_truncated" if stop_reason == "max_tokens" else "",
                cached_tokens=cache_read_input_tokens,
                cache_hit_ratio=_cache_hit_ratio(cache_read_input_tokens, input_tokens),
                prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
                prompt_cache_key_used=self.prompt_cache_enabled,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            ),
        )
