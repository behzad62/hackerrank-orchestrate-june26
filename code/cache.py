from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

VALID_CACHE_KEY = re.compile(r"^[A-Fa-f0-9]{64}$")
_CACHE_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _lock_for_key(key: str) -> threading.Lock:
    with _CACHE_LOCKS_GUARD:
        if key not in _CACHE_LOCKS:
            _CACHE_LOCKS[key] = threading.Lock()
        return _CACHE_LOCKS[key]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_cache_key(
    provider: str,
    model: str,
    prompt_version: str,
    row: dict[str, str],
    user_history: dict[str, str],
    evidence_requirements: list[dict[str, str]],
    image_hashes: list[str],
    normalizer_version: str,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "row": row,
        "user_history": user_history,
        "evidence_requirements": evidence_requirements,
        "image_hashes": image_hashes,
        "normalizer_version": normalizer_version,
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    if not VALID_CACHE_KEY.fullmatch(key):
        raise ValueError("Cache key must be exactly 64 hexadecimal characters.")
    return cache_dir / f"{key}.json"


def read_cache(cache_dir: Path, key: str) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_cache(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, key)
    tmp_path = path.with_name(f"{path.name}.{threading.get_ident()}.{time.time_ns()}.tmp")
    with _lock_for_key(str(path.resolve())):
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                tmp_path.replace(path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
