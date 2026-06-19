from __future__ import annotations

from typing import Protocol

from schemas import PredictionContext, ProviderResult

ERROR_CATEGORIES = {
    "auth_error",
    "insufficient_credit",
    "rate_limited",
    "bad_request",
    "unsupported_image",
    "context_length_exceeded",
    "response_truncated",
    "json_parse_error",
    "timeout",
    "network_error",
    "server_error",
    "unknown_provider_error",
}


class ProviderClient(Protocol):
    name: str

    def review_claim(self, context: PredictionContext) -> ProviderResult:
        ...
