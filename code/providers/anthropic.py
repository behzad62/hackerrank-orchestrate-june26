from __future__ import annotations

import time
from typing import Any

import requests

from providers.openai_compatible import categorize_http_error, extract_json_object
from prompting import build_text_prompt
from schemas import PredictionContext, ProviderMetadata, ProviderResult


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        timeout_seconds: int = 90,
        max_output_tokens: int = 1800,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    def _content(self, context: PredictionContext) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": build_text_prompt(context)}]
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

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        started = time.monotonic()
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
                "messages": [{"role": "user", "content": self._content(context)}],
            },
            timeout=self.timeout_seconds,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return ProviderResult(
                raw_json={"decision": {}},
                metadata=ProviderMetadata(
                    provider=self.name,
                    model=self.model,
                    latency_ms=duration_ms,
                    http_status=response.status_code,
                    error_category=categorize_http_error(response.status_code, response.text),
                ),
            )

        data = response.json()
        text = "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
        usage = data.get("usage", {})
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return ProviderResult(
            raw_json=extract_json_object(text),
            metadata=ProviderMetadata(
                provider=self.name,
                model=self.model,
                latency_ms=duration_ms,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                finish_reason=str(data.get("stop_reason") or ""),
                request_id=response.headers.get("request-id", ""),
                http_status=response.status_code,
            ),
        )
