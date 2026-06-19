from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("api_key", "authorization", "token", "secret", "cookie")
SAFE_NUMERIC_TOKEN_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
}
IMAGE_PAYLOAD_MARKERS = ("data_base64", "base64", "image_payload", "image_bytes", "raw_image")
MAX_STRING_LENGTH = 240
IMAGE_DATA_URI_PATTERN = re.compile(r"data:image(?:/[a-z0-9.+-]+)?;base64,", re.IGNORECASE)
SECRET_TOKEN_PATTERN = re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9._-]{6,}\b")
LIKELY_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/_-]+$")


def _looks_like_base64_payload(value: str) -> bool:
    if re.search(r"\s", value):
        if not re.search(r"[\r\n]", value):
            return False
        chunks = [chunk.strip() for chunk in value.splitlines() if chunk.strip()]
        if not chunks or any(not LIKELY_BASE64_PATTERN.fullmatch(chunk.replace("=", "")) for chunk in chunks):
            return False
        normalized = "".join(chunks)
    else:
        normalized = value
    if len(normalized) < MAX_STRING_LENGTH:
        return False
    return bool(LIKELY_BASE64_PATTERN.fullmatch(normalized.replace("=", "")))


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if SECRET_TOKEN_PATTERN.search(value) or "bearer " in lowered:
            return "[REDACTED]"
        if IMAGE_DATA_URI_PATTERN.search(value) or _looks_like_base64_payload(value):
            return "[REDACTED]"
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH] + "..."
    return value


def _safe_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
    if lowered_key in SAFE_NUMERIC_TOKEN_KEYS and isinstance(value, int | float):
        return value
    if any(marker in lowered_key for marker in SECRET_MARKERS):
        return "[REDACTED]"
    if any(marker in lowered_key for marker in IMAGE_PAYLOAD_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return _safe_record(value)
    if isinstance(value, list):
        return [_safe_value("", item) for item in value[:50]]
    return redact_value(value)


def _safe_record(data: dict[str, Any]) -> dict[str, Any]:
    return {key: _safe_value(key, value) for key, value in data.items()}


class JsonlLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, event_name: str, **fields: Any) -> None:
        record = {
            **fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
        }
        line = json.dumps(_safe_record(record), ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
