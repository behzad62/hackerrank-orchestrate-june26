from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace
from pathlib import Path

from schemas import AppPaths


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class AppConfig:
    provider: str
    model: str
    temperature: float = 0.0
    max_retries: int = 2
    timeout_seconds: int = 90
    allow_no_vision_fallback: bool = True
    max_output_tokens: int = 1800
    prompt_version: str = "claim-review-v1"
    paths: AppPaths | None = None

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "AppConfig":
        root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
        paths = AppPaths.from_repo_root(root)
        cache_override = os.environ.get("VLM_CACHE_DIR")
        if cache_override:
            paths = replace(paths, cache_dir=(root / cache_override).resolve())
        return cls(
            provider=os.environ.get("VLM_PROVIDER", "none").strip().lower(),
            model=os.environ.get("VLM_MODEL", "").strip(),
            temperature=float(os.environ.get("VLM_TEMPERATURE", "0")),
            max_retries=int(os.environ.get("VLM_MAX_RETRIES", "2")),
            timeout_seconds=int(os.environ.get("VLM_TIMEOUT_SECONDS", "90")),
            allow_no_vision_fallback=_env_bool("ALLOW_NO_VISION_FALLBACK", True),
            max_output_tokens=int(os.environ.get("VLM_MAX_OUTPUT_TOKENS", "1800")),
            paths=paths,
        )

    def with_overrides(
        self,
        claims: Path | None = None,
        sample: Path | None = None,
        output: Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        save_errors: bool | None = None,
    ) -> "AppConfig":
        del save_errors
        paths = self.paths
        if paths and (claims or sample or output):
            paths = replace(
                paths,
                claims_csv=claims or paths.claims_csv,
                sample_claims_csv=sample or paths.sample_claims_csv,
                output_csv=output or paths.output_csv,
            )
        return replace(
            self,
            paths=paths,
            provider=(provider or self.provider).strip().lower(),
            model=(model if model is not None else self.model).strip(),
        )


def build_common_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--claims", type=Path, default=None)
    parser.add_argument("--sample", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--provider", choices=["openai", "openrouter", "anthropic", "none"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--save-errors", action="store_true")
    return parser
