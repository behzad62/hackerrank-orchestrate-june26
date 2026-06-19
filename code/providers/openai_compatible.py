from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from prompting import build_text_prompt
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
    if "unsupported image" in lowered or "unsupported_image" in lowered:
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


def _safe_token_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_openai_usage(usage: Any) -> tuple[int, int, int]:
    if not isinstance(usage, dict):
        usage = {}
    return (
        _safe_token_count(usage.get("prompt_tokens")),
        _safe_token_count(usage.get("completion_tokens")),
        _safe_token_count(usage.get("total_tokens")),
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
    ):
        self.name = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://localhost/hackerrank-orchestrate"
            headers["X-Title"] = "HackerRank Orchestrate Claim Verification"
        return headers

    def _content(self, context: PredictionContext) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": build_text_prompt(context)}]
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
        )

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        started = time.monotonic()
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": self._content(context)}],
        }
        token_limit_key = (
            "max_completion_tokens"
            if _uses_openai_reasoning_token_limit(self.name, self.model)
            else "max_tokens"
        )
        payload[token_limit_key] = self.max_output_tokens
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
        finish_reason = ""
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response JSON is not an object")
            prompt_tokens, completion_tokens, total_tokens = _normalize_openai_usage(data.get("usage"))
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
                )
            message = choice.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError("missing message content")
            parsed = extract_json_object(message["content"])
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
            ),
        )
