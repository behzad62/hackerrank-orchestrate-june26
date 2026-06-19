from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from prompting import build_prompt_parts
from schemas import PredictionContext, ProviderMetadata, ProviderResult


def categorize_http_error(status_code: int, text: str) -> str:
    lowered = (text or "").lower()
    if status_code == 402 or "credit" in lowered or "quota" in lowered or "insufficient" in lowered:
        return "insufficient_credit"
    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 408:
        return "timeout"
    if status_code == 429:
        return "rate_limited"
    if status_code == 413 or "context length" in lowered or "token limit" in lowered:
        return "context_length_exceeded"
    if (
        "unsupported image" in lowered
        or "unsupported_image" in lowered
        or "support image input" in lowered
        or "does not support images" in lowered
        or "does not support image" in lowered
        or "unsupported modality" in lowered
    ):
        return "unsupported_image"
    if status_code in {400, 415}:
        return "bad_request"
    if status_code in {500, 502, 503, 504, 529}:
        return "server_error"
    return "unknown_provider_error"


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise json.JSONDecodeError("No JSON object found", stripped, 0)


DECISION_MARKER_FIELDS = {
    "claim_status",
    "issue_type",
    "object_part",
    "evidence_standard_met",
    "supporting_image_ids",
    "valid_image",
    "severity",
}


def has_decision_payload(parsed: dict[str, Any]) -> bool:
    decision = parsed.get("decision")
    if isinstance(decision, dict):
        return any(field in decision for field in DECISION_MARKER_FIELDS)
    return any(field in parsed for field in DECISION_MARKER_FIELDS)


def _safe_token_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cache_hit_ratio(cached_tokens: int, prompt_tokens: int) -> float:
    if prompt_tokens <= 0 or cached_tokens <= 0:
        return 0.0
    return round(cached_tokens / prompt_tokens, 4)


def _normalize_openai_usage(usage: Any) -> tuple[int, int, int, int, int]:
    if not isinstance(usage, dict):
        usage = {}
    prompt_tokens_details = usage.get("prompt_tokens_details")
    if not isinstance(prompt_tokens_details, dict):
        prompt_tokens_details = {}
    return (
        _safe_token_count(usage.get("prompt_tokens")),
        _safe_token_count(usage.get("completion_tokens")),
        _safe_token_count(usage.get("total_tokens")),
        _safe_token_count(prompt_tokens_details.get("cached_tokens")),
        _safe_token_count(prompt_tokens_details.get("cache_write_tokens")),
    )


def _uses_openai_reasoning_token_limit(provider: str, model: str) -> bool:
    if provider != "openai":
        return False
    model_slug = (model or "").lower()
    return bool(re.match(r"^o\d", model_slug)) or model_slug.startswith("gpt-5")


class OpenAICompatibleProvider:
    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
        temperature: float = 0.0,
        timeout_seconds: int = 90,
        max_output_tokens: int = 1800,
        prompt_cache_enabled: bool = True,
        prompt_cache_retention: str = "24h",
        reasoning_enabled: bool = False,
        reasoning_effort: str = "low",
        reasoning_max_tokens: int = 0,
        reasoning_exclude: bool = True,
    ):
        self.name = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.prompt_cache_enabled = prompt_cache_enabled
        self.prompt_cache_retention = prompt_cache_retention
        self.reasoning_enabled = reasoning_enabled
        self.reasoning_effort = reasoning_effort.strip().lower()
        self.reasoning_max_tokens = reasoning_max_tokens
        self.reasoning_exclude = reasoning_exclude

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://localhost/hackerrank-orchestrate"
            headers["X-OpenRouter-Title"] = "HackerRank Orchestrate Claim Verification"
        return headers

    def _dynamic_content(self, context: PredictionContext) -> list[dict[str, Any]]:
        prompt_parts = build_prompt_parts(context)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt_parts.dynamic_suffix}]
        for image in context.prepared_images:
            if not image.readable or not image.data_base64:
                continue
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{image.data_base64}",
                        "detail": "high",
                    },
                }
            )
        return content

    def _messages(self, context: PredictionContext) -> list[dict[str, Any]]:
        prompt_parts = build_prompt_parts(context)
        static_block: dict[str, Any] = {"type": "text", "text": prompt_parts.static_prefix}
        if self.name == "openrouter" and self.prompt_cache_enabled:
            static_block["cache_control"] = {"type": "ephemeral"}
        return [
            {"role": "system", "content": [static_block]},
            {"role": "user", "content": self._dynamic_content(context)},
        ]

    def _reasoning_config(self) -> dict[str, Any] | None:
        if not self.reasoning_enabled:
            return None
        config: dict[str, Any] = {"enabled": True}
        if self.reasoning_max_tokens > 0:
            config["max_tokens"] = self.reasoning_max_tokens
        elif self.reasoning_effort:
            config["effort"] = self.reasoning_effort
        config["exclude"] = self.reasoning_exclude
        return config

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
        cache_write_tokens: int = 0,
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
                cache_creation_input_tokens=cache_write_tokens,
                cache_read_input_tokens=cached_tokens,
            ),
        )

    def _metadata(
        self,
        *,
        latency_ms: int,
        http_status: int,
        response: requests.Response,
        choice: dict[str, Any],
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_tokens: int,
        cache_write_tokens: int,
    ) -> ProviderMetadata:
        finish_reason = str(choice.get("finish_reason") or "")
        return ProviderMetadata(
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
            request_id=response.headers.get("x-request-id", ""),
            http_status=http_status,
            error_category="response_truncated" if finish_reason == "length" else "",
            cached_tokens=cached_tokens,
            cache_hit_ratio=_cache_hit_ratio(cached_tokens, prompt_tokens),
            prompt_cache_retention=self.prompt_cache_retention if self.prompt_cache_enabled else "",
            prompt_cache_key_used=self.prompt_cache_enabled,
            cache_creation_input_tokens=cache_write_tokens,
            cache_read_input_tokens=cached_tokens,
        )

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        started = time.monotonic()
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": self._messages(context),
        }
        token_limit_key = (
            "max_completion_tokens"
            if self.name == "openrouter" or _uses_openai_reasoning_token_limit(self.name, self.model)
            else "max_tokens"
        )
        payload[token_limit_key] = self.max_output_tokens
        if self.name == "openrouter" and self.prompt_cache_enabled:
            payload["session_id"] = "hackerrank-orchestrate-claim-review-v1"
        reasoning_config = self._reasoning_config()
        if reasoning_config and self.name == "openrouter":
            payload["reasoning"] = reasoning_config
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
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
                request_id=response.headers.get("x-request-id", ""),
            )

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cached_tokens = 0
        cache_write_tokens = 0
        finish_reason = ""
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response JSON is not an object")
            (
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cached_tokens,
                cache_write_tokens,
            ) = _normalize_openai_usage(data.get("usage"))
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("missing choices")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise ValueError("invalid choice")
            finish_reason = str(choice.get("finish_reason") or "")
            if finish_reason == "length":
                return self._error_result(
                    category="response_truncated",
                    latency_ms=duration_ms,
                    http_status=response.status_code,
                    finish_reason=finish_reason,
                    request_id=response.headers.get("x-request-id", ""),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cached_tokens=cached_tokens,
                    cache_write_tokens=cache_write_tokens,
                )
            message = choice.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("missing message content")
            parsed = extract_json_object(message["content"])
            if not has_decision_payload(parsed):
                raise ValueError("missing decision payload")
        except (ValueError, TypeError, json.JSONDecodeError):
            return self._error_result(
                category="json_parse_error",
                latency_ms=duration_ms,
                http_status=response.status_code,
                finish_reason=finish_reason,
                request_id=response.headers.get("x-request-id", ""),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
            )

        return ProviderResult(
            raw_json=parsed,
            metadata=self._metadata(
                latency_ms=duration_ms,
                http_status=response.status_code,
                response=response,
                choice=choice,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
            ),
        )
