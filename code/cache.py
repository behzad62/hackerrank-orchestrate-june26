from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


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
    return cache_dir / f"{key}.json"


def read_cache(cache_dir: Path, key: str) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_cache(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, key)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
