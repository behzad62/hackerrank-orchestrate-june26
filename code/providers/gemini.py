from __future__ import annotations

import json
import time
from typing import Any

import requests

from providers.openai_compatible import _cache_hit_ratio, _safe_token_count, extract_json_object
from prompting import build_prompt_parts
from schemas import PredictionContext, ProviderMetadata, ProviderResult


def categorize_gemini_http_error(status_code: int, text: str) -> str:
    lowered = (text or "").lower()
    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 408:
        return "timeout"
    if status_code == 429 or "resource_exhausted" in lowered:
        return "rate_limited"
    if status_code == 413 or "context" in lowered or "payload size" in lowered or "too large" in lowered:
        return "context_length_exceeded"
    if "unsupported image" in lowered or "unsupported modality" in lowered:
        return "unsupported_image"
    if status_code in {400, 404}:
        return "bad_request"
    if status_code in {500, 502, 503, 504}:
        return "server_error"
    return "unknown_provider_error"


def _normalize_usage(usage: Any) -> tuple[int, int, int, int]:
    if not isinstance(usage, dict):
        usage = {}
    return (
        _safe_token_count(usage.get("promptTokenCount")),
        _safe_token_count(usage.get("candidatesTokenCount")),
        _safe_token_count(usage.get("totalTokenCount")),
        _safe_token_count(usage.get("cachedContentTokenCount")),
    )


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 90,
        max_output_tokens: int = 1800,
        prompt_cache_enabled: bool = True,
        prompt_cache_retention: str = "implicit",
        thinking_level: str = "medium",
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.prompt_cache_enabled = prompt_cache_enabled
        self.prompt_cache_retention = prompt_cache_retention
        self.thinking_level = thinking_level

    def _url(self) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _parts(self, context: PredictionContext) -> list[dict[str, Any]]:
        prompt_parts = build_prompt_parts(context)
        parts: list[dict[str, Any]] = [{"text": prompt_parts.dynamic_suffix}]
        for image in context.prepared_images:
            if not image.readable or not image.data_base64:
                continue
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image.mime_type,
                        "data": image.data_base64,
                    }
                }
            )
        return parts

    def _payload(self, context: PredictionContext) -> dict[str, Any]:
        prompt_parts = build_prompt_parts(context)
        return {
            "systemInstruction": {"parts": [{"text": prompt_parts.static_prefix}]},
            "contents": [{"role": "user", "parts": self._parts(context)}],
            "generationConfig": {
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": self.thinking_level},
            },
        }

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
        cached_tokens: int = 0,
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
                cached_tokens=cached_tokens,
                cache_hit_ratio=_cache_hit_ratio(cached_tokens, prompt_tokens),
                prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
                prompt_cache_key_used=self.prompt_cache_enabled,
                cache_read_input_tokens=cached_tokens,
            ),
        )

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        started = time.monotonic()
        try:
            response = requests.post(
                self._url(),
                headers=self._headers(),
                json=self._payload(context),
                timeout=self.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="timeout", latency_ms=duration_ms)
        except requests.exceptions.RequestException:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._error_result(category="network_error", latency_ms=duration_ms)

        duration_ms = int((time.monotonic() - started) * 1000)
        request_id = response.headers.get("x-request-id", "") or response.headers.get("x-goog-request-id", "")
        if response.status_code >= 400:
            return self._error_result(
                category=categorize_gemini_http_error(response.status_code, response.text),
                latency_ms=duration_ms,
                http_status=response.status_code,
                request_id=request_id,
            )

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cached_tokens = 0
        finish_reason = ""
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response JSON is not an object")
            prompt_tokens, completion_tokens, total_tokens, cached_tokens = _normalize_usage(
                data.get("usageMetadata")
            )
            candidates = data.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                raise ValueError("missing candidates")
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                raise ValueError("invalid candidate")
            finish_reason = str(candidate.get("finishReason") or "")
            if finish_reason == "MAX_TOKENS":
                return self._error_result(
                    category="response_truncated",
                    latency_ms=duration_ms,
                    http_status=response.status_code,
                    finish_reason=finish_reason,
                    request_id=request_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                )
            content = candidate.get("content")
            if not isinstance(content, dict):
                raise ValueError("missing content")
            parts = content.get("parts")
            if not isinstance(parts, list):
                raise ValueError("missing parts")
            text = "\n".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
            parsed = extract_json_object(text)
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._error_result(
                category="json_parse_error",
                latency_ms=duration_ms,
                http_status=response.status_code,
                finish_reason=finish_reason,
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
            )

        return ProviderResult(
            raw_json=parsed,
            metadata=ProviderMetadata(
                provider=self.name,
                model=self.model,
                latency_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                request_id=request_id,
                http_status=response.status_code,
                cached_tokens=cached_tokens,
                cache_hit_ratio=_cache_hit_ratio(cached_tokens, prompt_tokens),
                prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
                prompt_cache_key_used=self.prompt_cache_enabled,
                cache_read_input_tokens=cached_tokens,
            ),
        )
