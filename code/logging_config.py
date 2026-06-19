from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("api_key", "authorization", "token", "secret", "cookie")
IMAGE_PAYLOAD_MARKERS = ("data_base64", "base64", "image_payload", "image_bytes", "raw_image")
MAX_STRING_LENGTH = 240


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.lower()
        if value.startswith(("sk-", "sk-ant-")) or "bearer " in lowered:
            return "[REDACTED]"
        if len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH] + "..."
    return value


def _safe_value(key: str, value: Any) -> Any:
    lowered_key = key.lower()
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

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(_safe_record(record), ensure_ascii=False) + "\n")
