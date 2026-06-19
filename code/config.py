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


def load_env_file(path: Path | None) -> None:
    if path is None:
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip().strip("\"'"))


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    model: str


def parse_provider_spec(raw: str) -> ProviderSpec:
    provider, separator, model = raw.strip().partition(":")
    if not separator or not provider.strip() or not model.strip():
        raise ValueError(f"Invalid provider spec: {raw!r}")
    return ProviderSpec(provider=provider.strip().lower(), model=model.strip())


def parse_backup_chain(raw: str) -> tuple[ProviderSpec, ...]:
    if not raw.strip():
        return ()
    return tuple(parse_provider_spec(part) for part in raw.split(",") if part.strip())


def parse_model_prices(raw: str) -> dict[tuple[str, str], tuple[float, float]]:
    prices: dict[tuple[str, str], tuple[float, float]] = {}
    if not raw.strip():
        return prices
    for entry in raw.split(";"):
        stripped = entry.strip()
        if not stripped:
            continue
        key, separator, values = stripped.partition("=")
        if not separator:
            raise ValueError(f"Invalid model price entry: {entry!r}")
        spec = parse_provider_spec(key)
        input_price, value_separator, output_price = values.partition(",")
        if not value_separator:
            raise ValueError(f"Invalid model price values: {entry!r}")
        prices[(spec.provider, spec.model)] = (float(input_price.strip()), float(output_price.strip()))
    return prices


@dataclass(frozen=True)
class AppConfig:
    provider: str
    model: str
    temperature: float = 0.0
    max_retries: int = 2
    retry_max_sleep_seconds: int = 8
    timeout_seconds: int = 90
    allow_no_vision_fallback: bool = True
    allow_backup_vlm: bool = False
    backup_chain: tuple[ProviderSpec, ...] = ()
    max_concurrency: int = 1
    requests_per_minute: int = 0
    backup_max_concurrency: int = 1
    max_output_tokens: int = 1800
    prompt_cache_enabled: bool = True
    prompt_cache_retention: str = "24h"
    prompt_version: str = "claim-review-v2-openrouter-cache"
    strategy_mode: str = "one_pass"
    adjudicator_provider: str = ""
    adjudicator_model: str = ""
    reasoning_enabled: bool = False
    reasoning_effort: str = "low"
    reasoning_max_tokens: int = 0
    reasoning_exclude: bool = True
    ignore_cache: bool = False
    cache_write_enabled: bool = True
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
            retry_max_sleep_seconds=int(os.environ.get("VLM_RETRY_MAX_SLEEP_SECONDS", "8")),
            timeout_seconds=int(os.environ.get("VLM_TIMEOUT_SECONDS", "90")),
            allow_no_vision_fallback=_env_bool("ALLOW_NO_VISION_FALLBACK", True),
            allow_backup_vlm=_env_bool("ALLOW_BACKUP_VLM", False),
            backup_chain=parse_backup_chain(os.environ.get("VLM_BACKUP_CHAIN", "")),
            max_concurrency=int(os.environ.get("VLM_MAX_CONCURRENCY", "1")),
            requests_per_minute=int(os.environ.get("VLM_REQUESTS_PER_MINUTE", "0")),
            backup_max_concurrency=int(os.environ.get("VLM_BACKUP_MAX_CONCURRENCY", "1")),
            max_output_tokens=int(os.environ.get("VLM_MAX_OUTPUT_TOKENS", "1800")),
            prompt_cache_enabled=_env_bool("PROMPT_CACHE_ENABLED", True),
            prompt_cache_retention=os.environ.get("PROMPT_CACHE_RETENTION", "24h").strip(),
            strategy_mode=os.environ.get("CLAIM_REVIEW_STRATEGY_MODE", "one_pass").strip().lower(),
            adjudicator_provider=os.environ.get("ADJUDICATOR_PROVIDER", "").strip().lower(),
            adjudicator_model=os.environ.get("ADJUDICATOR_MODEL", "").strip(),
            reasoning_enabled=_env_bool("VLM_REASONING_ENABLED", False),
            reasoning_effort=os.environ.get("VLM_REASONING_EFFORT", "low").strip().lower(),
            reasoning_max_tokens=int(os.environ.get("VLM_REASONING_MAX_TOKENS", "0")),
            reasoning_exclude=_env_bool("VLM_REASONING_EXCLUDE", True),
            ignore_cache=_env_bool("EVAL_IGNORE_CACHE", False),
            cache_write_enabled=_env_bool("CACHE_WRITE_ENABLED", True),
            paths=paths,
        )

    def with_overrides(
        self,
        claims: Path | None = None,
        sample: Path | None = None,
        history: Path | None = None,
        evidence: Path | None = None,
        images: Path | None = None,
        output: Path | None = None,
        log: Path | None = None,
        cache: Path | None = None,
        provider: str | None = None,
        model: str | None = None,
        retries: int | None = None,
        fallback: bool | None = None,
        max_concurrency: int | None = None,
        requests_per_minute: int | None = None,
        backup_max_concurrency: int | None = None,
        prompt_cache_enabled: bool | None = None,
        prompt_cache_retention: str | None = None,
        strategy_mode: str | None = None,
        adjudicator_provider: str | None = None,
        adjudicator_model: str | None = None,
        ignore_cache: bool | None = None,
        cache_write_enabled: bool | None = None,
        save_errors: bool | None = None,
    ) -> "AppConfig":
        del save_errors
        paths = self.paths
        if paths and (claims or sample or history or evidence or images or output or log or cache):
            paths = replace(
                paths,
                claims_csv=claims or paths.claims_csv,
                sample_claims_csv=sample or paths.sample_claims_csv,
                user_history_csv=history or paths.user_history_csv,
                evidence_requirements_csv=evidence or paths.evidence_requirements_csv,
                images_dir=images or paths.images_dir,
                output_csv=output or paths.output_csv,
                logs_dir=log or paths.logs_dir,
                cache_dir=cache or paths.cache_dir,
            )
        return replace(
            self,
            paths=paths,
            provider=(provider or self.provider).strip().lower(),
            model=(model if model is not None else self.model).strip(),
            max_retries=retries if retries is not None else self.max_retries,
            allow_no_vision_fallback=fallback if fallback is not None else self.allow_no_vision_fallback,
            max_concurrency=max_concurrency if max_concurrency is not None else self.max_concurrency,
            requests_per_minute=requests_per_minute if requests_per_minute is not None else self.requests_per_minute,
            backup_max_concurrency=(
                backup_max_concurrency if backup_max_concurrency is not None else self.backup_max_concurrency
            ),
            prompt_cache_enabled=(
                prompt_cache_enabled if prompt_cache_enabled is not None else self.prompt_cache_enabled
            ),
            prompt_cache_retention=(
                prompt_cache_retention if prompt_cache_retention is not None else self.prompt_cache_retention
            ).strip(),
            strategy_mode=(strategy_mode or self.strategy_mode).strip().lower(),
            adjudicator_provider=(
                adjudicator_provider if adjudicator_provider is not None else self.adjudicator_provider
            ).strip().lower(),
            adjudicator_model=(adjudicator_model if adjudicator_model is not None else self.adjudicator_model).strip(),
            ignore_cache=ignore_cache if ignore_cache is not None else self.ignore_cache,
            cache_write_enabled=(
                cache_write_enabled if cache_write_enabled is not None else self.cache_write_enabled
            ),
        )


def build_common_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--claims", type=Path, default=None)
    parser.add_argument("--sample", type=Path, default=None)
    parser.add_argument("--history", type=Path, default=None)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--images", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--env", type=Path, default=None)
    parser.add_argument("--provider", choices=["openai", "openrouter", "anthropic", "gemini", "none"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--retries", type=int, default=None)
    parser.add_argument("--max-concurrency", type=int, default=None)
    parser.add_argument("--requests-per-minute", type=int, default=None)
    parser.add_argument("--backup-max-concurrency", type=int, default=None)
    parser.add_argument("--fallback", dest="fallback", action="store_true", default=None)
    parser.add_argument("--no-fallback", dest="fallback", action="store_false")
    parser.add_argument("--prompt-cache", dest="prompt_cache_enabled", action="store_true", default=None)
    parser.add_argument("--no-prompt-cache", dest="prompt_cache_enabled", action="store_false")
    parser.add_argument("--prompt-cache-retention", default=None)
    parser.add_argument("--strategy-mode", choices=["one_pass", "two_pass"], default=None)
    parser.add_argument("--adjudicator-provider", choices=["openai", "openrouter", "anthropic", "gemini", "none"], default=None)
    parser.add_argument("--adjudicator-model", default=None)
    parser.add_argument("--ignore-cache", action="store_true", default=None)
    parser.add_argument("--no-cache-write", dest="cache_write_enabled", action="store_false", default=None)
    parser.add_argument("--save-errors", action="store_true")
    return parser
