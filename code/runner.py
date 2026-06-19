from __future__ import annotations

import threading
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cache import build_cache_key, read_cache, write_cache
from config import AppConfig, ProviderSpec
from data import load_claim_rows, load_evidence_requirements, load_user_history, write_output_rows
from images import prepare_images
from logging_config import JsonlLogger
from normalization import normalize_provider_result
from providers import AnthropicProvider, FallbackProvider, GeminiProvider, OpenAICompatibleProvider
from schemas import AppPaths, PredictionContext, ProviderMetadata, ProviderResult
from security import detect_prompt_injection_flags

NORMALIZER_VERSION = "normalizer-v1-cache-policy-v2"
RETRYABLE_ERROR_CATEGORIES = {
    "rate_limited",
    "timeout",
    "network_error",
    "server_error",
    "response_truncated",
    "json_parse_error",
}
BACKUP_TRIGGER_ERROR_CATEGORIES = {
    "auth_error",
    "insufficient_credit",
    "rate_limited",
    "response_truncated",
    "json_parse_error",
    "timeout",
    "network_error",
    "server_error",
    "unknown_provider_error",
}


@dataclass(frozen=True)
class RowResult:
    row_index: int
    output_row: dict[str, str]
    provider_calls: int = 0
    backup_used: bool = False
    used_fallback: bool = False
    duration_ms: int = 0
    cache_hit: bool = False


class ProviderLimiter:
    def __init__(self, requests_per_minute: int = 0):
        self.requests_per_minute = max(0, requests_per_minute)
        self._lock = threading.Lock()
        self._next_start = 0.0

    def acquire(self, provider: str, row_index: int, logger: JsonlLogger) -> None:
        if self.requests_per_minute <= 0:
            return
        min_interval = 60.0 / self.requests_per_minute
        wait_seconds = 0.0
        with self._lock:
            now = time.monotonic()
            if now < self._next_start:
                wait_seconds = self._next_start - now
                self._next_start += min_interval
            else:
                self._next_start = now + min_interval
        if wait_seconds > 0:
            logger.write(
                "rate_limiter_wait",
                row_index=row_index,
                provider=provider,
                wait_ms=int(wait_seconds * 1000),
                reason="rpm_limit",
            )
            time.sleep(wait_seconds)


def _coerce_provider_spec(spec: ProviderSpec | tuple[str, str]) -> ProviderSpec:
    if isinstance(spec, ProviderSpec):
        return spec
    provider, model = spec
    return ProviderSpec(provider=str(provider).strip().lower(), model=str(model).strip())


def build_provider_for_spec(cfg: AppConfig, spec: ProviderSpec | tuple[str, str], allow_key_fallback: bool = False):
    spec = _coerce_provider_spec(spec)
    provider = spec.provider.strip().lower()
    model = spec.model.strip()
    if provider == "none":
        return FallbackProvider()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            if allow_key_fallback and cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("OPENAI_API_KEY is required when VLM_PROVIDER=openai")
        return OpenAICompatibleProvider(
            provider="openai",
            api_key=key,
            model=model,
            base_url="https://api.openai.com/v1",
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
            prompt_cache_enabled=cfg.prompt_cache_enabled,
            prompt_cache_retention=cfg.prompt_cache_retention,
            reasoning_enabled=cfg.reasoning_enabled,
            reasoning_effort=cfg.reasoning_effort,
            reasoning_max_tokens=cfg.reasoning_max_tokens,
            reasoning_exclude=cfg.reasoning_exclude,
        )
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            if allow_key_fallback and cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("OPENROUTER_API_KEY is required when VLM_PROVIDER=openrouter")
        return OpenAICompatibleProvider(
            provider="openrouter",
            api_key=key,
            model=model,
            base_url="https://openrouter.ai/api/v1",
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
            prompt_cache_enabled=cfg.prompt_cache_enabled,
            prompt_cache_retention=cfg.prompt_cache_retention,
            reasoning_enabled=cfg.reasoning_enabled,
            reasoning_effort=cfg.reasoning_effort,
            reasoning_max_tokens=cfg.reasoning_max_tokens,
            reasoning_exclude=cfg.reasoning_exclude,
        )
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            if allow_key_fallback and cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("ANTHROPIC_API_KEY is required when VLM_PROVIDER=anthropic")
        return AnthropicProvider(
            api_key=key,
            model=model,
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
            prompt_cache_enabled=cfg.prompt_cache_enabled,
            prompt_cache_retention=cfg.prompt_cache_retention,
        )
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            if allow_key_fallback and cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required when VLM_PROVIDER=gemini")
        return GeminiProvider(
            api_key=key,
            model=model or "gemini-3.5-flash",
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
            prompt_cache_enabled=cfg.prompt_cache_enabled,
            prompt_cache_retention=cfg.prompt_cache_retention,
            reasoning_enabled=cfg.reasoning_enabled,
            reasoning_effort=cfg.reasoning_effort,
        )
    raise ValueError(f"Unsupported provider: {provider}")


def build_provider(cfg: AppConfig):
    return build_provider_for_spec(
        cfg,
        ProviderSpec(provider=cfg.provider, model=cfg.model),
        allow_key_fallback=True,
    )


def _fallback_result(context: PredictionContext, provider_name: str, error_category: str = "") -> ProviderResult:
    fallback = FallbackProvider().review_claim(context)
    return ProviderResult(
        raw_json=fallback.raw_json,
        metadata=ProviderMetadata(
            provider=provider_name,
            model="fallback",
            error_category=error_category,
        ),
        used_fallback=True,
    )


def _exception_category(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "unknown_provider_error"


def _sleep_seconds(attempt: int, max_sleep_seconds: int) -> int:
    return min(max(1, max_sleep_seconds), 2**attempt)


def _effective_prompt_version(cfg: AppConfig) -> str:
    generation_settings = {
        "prompt_version": cfg.prompt_version,
        "temperature": cfg.temperature,
        "max_output_tokens": cfg.max_output_tokens,
        "provider": cfg.provider,
        "reasoning_enabled": cfg.reasoning_enabled,
        "reasoning_effort": cfg.reasoning_effort,
        "reasoning_max_tokens": cfg.reasoning_max_tokens,
        "reasoning_exclude": cfg.reasoning_exclude,
    }
    return "|".join(f"{key}={value}" for key, value in generation_settings.items())


def _call_with_retries(
    provider: Any,
    context: PredictionContext,
    cfg: AppConfig,
    logger: JsonlLogger,
    allow_no_vision_fallback: bool | None = None,
    raise_on_failure: bool = True,
    provider_limiter: ProviderLimiter | None = None,
) -> ProviderResult:
    if allow_no_vision_fallback is None:
        allow_no_vision_fallback = cfg.allow_no_vision_fallback
    provider_name = getattr(provider, "name", cfg.provider)
    last_result: ProviderResult | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            if provider_limiter:
                provider_limiter.acquire(provider_name, context.row_index, logger)
            result = provider.review_claim(context)
        except Exception as exc:
            category = _exception_category(exc)
            logger.write(
                "provider_exception",
                row_index=context.row_index,
                provider=provider_name,
                error_category=category,
                safe_message=str(exc)[:240],
                retry_count=attempt,
            )
            result = ProviderResult(
                raw_json={"decision": {}},
                metadata=ProviderMetadata(provider=provider_name, model=cfg.model, error_category=category),
            )

        last_result = result
        category = result.metadata.error_category
        if not category:
            return result

        logger.write(
            "provider_error",
            row_index=context.row_index,
            provider=result.metadata.provider or provider_name,
            model=result.metadata.model,
            error_category=category,
            retry_count=attempt,
            http_status=result.metadata.http_status,
            finish_reason=result.metadata.finish_reason,
        )
        if category not in RETRYABLE_ERROR_CATEGORIES or attempt >= cfg.max_retries:
            break
        sleep_seconds = _sleep_seconds(attempt, cfg.retry_max_sleep_seconds)
        logger.write(
            "provider_retry_scheduled",
            row_index=context.row_index,
            provider=provider_name,
            error_category=category,
            retry_count=attempt + 1,
            sleep_seconds=sleep_seconds,
        )
        time.sleep(sleep_seconds)

    if allow_no_vision_fallback:
        category = last_result.metadata.error_category if last_result else "unknown_provider_error"
        logger.write(
            "provider_fallback_used",
            row_index=context.row_index,
            provider=provider_name,
            error_category=category,
        )
        return _fallback_result(context, provider_name, category)

    if last_result and not raise_on_failure:
        return last_result
    category = last_result.metadata.error_category if last_result else "unknown_provider_error"
    raise RuntimeError(f"Provider failed and fallback is disabled: {category}")


def _provider_chain_specs(cfg: AppConfig) -> list[ProviderSpec]:
    primary = ProviderSpec(provider=cfg.provider, model=cfg.model)
    if not cfg.allow_backup_vlm:
        return [primary]
    return [primary, *[_coerce_provider_spec(spec) for spec in cfg.backup_chain]]


def _call_provider_chain(
    cfg: AppConfig,
    context: PredictionContext,
    logger: JsonlLogger,
    provider_limiter: ProviderLimiter | None = None,
    backup_semaphore: threading.BoundedSemaphore | None = None,
) -> tuple[ProviderResult, str, str, bool, str]:
    specs = _provider_chain_specs(cfg)
    primary_provider = specs[0].provider if specs else cfg.provider
    last_result: ProviderResult | None = None
    backup_reason = ""

    if not cfg.allow_backup_vlm:
        result = _call_with_retries(
            build_provider(cfg),
            context,
            cfg,
            logger,
            provider_limiter=provider_limiter,
        )
        final_provider = result.metadata.provider or primary_provider
        return result, primary_provider, final_provider, False, ""

    logger.write(
        "provider_chain_started",
        row_index=context.row_index,
        primary_provider=primary_provider,
        backup_count=max(0, len(specs) - 1),
    )
    for index, spec in enumerate(specs):
        is_backup = index > 0
        logger.write(
            "provider_chain_step_started",
            row_index=context.row_index,
            provider=spec.provider,
            model=spec.model,
            is_backup=is_backup,
        )
        try:
            provider = build_provider_for_spec(cfg, spec, allow_key_fallback=False)
        except RuntimeError as exc:
            result = ProviderResult(
                raw_json={"decision": {}},
                metadata=ProviderMetadata(
                    provider=spec.provider,
                    model=spec.model,
                    error_category="auth_error",
                ),
            )
            logger.write(
                "provider_exception",
                row_index=context.row_index,
                provider=spec.provider,
                error_category="auth_error",
                safe_message=str(exc)[:240],
                retry_count=0,
            )
        else:
            if is_backup and backup_semaphore:
                with backup_semaphore:
                    result = _call_with_retries(
                        provider,
                        context,
                        cfg,
                        logger,
                        allow_no_vision_fallback=False,
                        raise_on_failure=False,
                        provider_limiter=provider_limiter,
                    )
            else:
                result = _call_with_retries(
                    provider,
                    context,
                    cfg,
                    logger,
                    allow_no_vision_fallback=False,
                    raise_on_failure=False,
                    provider_limiter=provider_limiter,
                )
        last_result = result
        category = result.metadata.error_category
        if not category:
            final_provider = result.metadata.provider or spec.provider
            if is_backup:
                logger.write(
                    "provider_backup_selected",
                    row_index=context.row_index,
                    primary_provider=primary_provider,
                    final_provider=final_provider,
                    backup_reason=backup_reason,
                )
            return result, primary_provider, final_provider, is_backup, backup_reason
        logger.write(
            "provider_chain_step_failed",
            row_index=context.row_index,
            provider=result.metadata.provider or spec.provider,
            model=result.metadata.model or spec.model,
            error_category=category,
            is_backup=is_backup,
        )
        if category not in BACKUP_TRIGGER_ERROR_CATEGORIES:
            break
        backup_reason = backup_reason or category

    if cfg.allow_no_vision_fallback:
        category = last_result.metadata.error_category if last_result else "unknown_provider_error"
        logger.write(
            "provider_fallback_used",
            row_index=context.row_index,
            provider=primary_provider,
            error_category=category,
        )
        result = _fallback_result(context, primary_provider, category)
        return result, primary_provider, result.metadata.provider, False, category

    category = last_result.metadata.error_category if last_result else "unknown_provider_error"
    raise RuntimeError(f"Provider chain failed and fallback is disabled: {category}")


def _metadata_from_cache(payload: dict[str, Any]) -> ProviderMetadata:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return ProviderMetadata(
        provider=str(metadata.get("provider") or ""),
        model=str(metadata.get("model") or ""),
        latency_ms=int(metadata.get("latency_ms") or 0),
        prompt_tokens=int(metadata.get("prompt_tokens") or 0),
        completion_tokens=int(metadata.get("completion_tokens") or 0),
        total_tokens=int(metadata.get("total_tokens") or 0),
        finish_reason=str(metadata.get("finish_reason") or ""),
        request_id=str(metadata.get("request_id") or ""),
        http_status=int(metadata.get("http_status") or 0),
        error_category=str(metadata.get("error_category") or ""),
        cache_hit=True,
        cached_tokens=int(metadata.get("cached_tokens") or 0),
        cache_hit_ratio=float(metadata.get("cache_hit_ratio") or 0.0),
        prompt_cache_retention=str(metadata.get("prompt_cache_retention") or ""),
        prompt_cache_key_used=bool(metadata.get("prompt_cache_key_used") or False),
        cache_creation_input_tokens=int(metadata.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(metadata.get("cache_read_input_tokens") or 0),
    )


def _cache_payload_is_trustworthy(payload: dict[str, Any]) -> bool:
    if payload.get("used_fallback", False):
        return False
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return False
    provider = str(metadata.get("provider") or "").strip().lower()
    model = str(metadata.get("model") or "").strip().lower()
    if metadata.get("error_category"):
        return False
    if provider == "none" or model == "fallback":
        return False
    return True


def _selected_requirements(all_requirements: list[dict[str, str]], claim_object: str) -> list[dict[str, str]]:
    return [
        requirement
        for requirement in all_requirements
        if requirement.get("claim_object") in {"all", claim_object}
    ]


def _write_provider_response_log(
    logger: JsonlLogger,
    context: PredictionContext,
    result: ProviderResult,
    cache_hit: bool,
) -> None:
    metadata = result.metadata
    logger.write(
        "provider_response",
        row_index=context.row_index,
        provider=metadata.provider,
        model=metadata.model,
        duration_ms=metadata.latency_ms,
        http_status=metadata.http_status,
        finish_reason=metadata.finish_reason,
        prompt_tokens=metadata.prompt_tokens,
        completion_tokens=metadata.completion_tokens,
        total_tokens=metadata.total_tokens,
        cached_tokens=metadata.cached_tokens,
        cache_hit_ratio=metadata.cache_hit_ratio,
        prompt_cache_retention=metadata.prompt_cache_retention,
        prompt_cache_key_used=metadata.prompt_cache_key_used,
        cache_creation_input_tokens=metadata.cache_creation_input_tokens,
        cache_read_input_tokens=metadata.cache_read_input_tokens,
        cache_hit=cache_hit,
        used_fallback=result.used_fallback,
    )


def process_claim_row(
    *,
    cfg: AppConfig,
    row_index: int,
    row: dict[str, str],
    user_history: dict[str, dict[str, str]],
    all_requirements: list[dict[str, str]],
    logger: JsonlLogger,
    paths: AppPaths,
    provider_limiter: ProviderLimiter | None = None,
    backup_semaphore: threading.BoundedSemaphore | None = None,
) -> RowResult:
    started = time.monotonic()
    worker_name = threading.current_thread().name
    logger.write(
        "worker_claim_started",
        row_index=row_index,
        worker_name=worker_name,
        thread_id=threading.get_ident(),
    )
    primary_provider = cfg.provider
    final_provider = ""
    backup_used = False
    backup_reason = ""
    cache_hit = False

    prepared_images = prepare_images(paths.repo_root, row.get("image_paths", ""), paths.images_dir)
    history = user_history.get(row.get("user_id", ""), {})
    requirements = _selected_requirements(all_requirements, row.get("claim_object", ""))
    context = PredictionContext(
        row_index=row_index,
        row=row,
        user_history=history,
        evidence_requirements=requirements,
        all_evidence_requirements=all_requirements,
        prepared_images=prepared_images,
        claim_text_risk_flags=detect_prompt_injection_flags(row.get("user_claim", "")),
    )

    logger.write(
        "claim_started",
        row_index=row_index,
        user_id=row.get("user_id", ""),
        claim_object=row.get("claim_object", ""),
        image_ids=[image.image_id for image in prepared_images],
        image_count=len(prepared_images),
    )
    for image in prepared_images:
        logger.write(
            "image_prepared",
            row_index=row_index,
            image_id=image.image_id,
            mime_type=image.mime_type,
            size_bytes=image.size_bytes,
            sha256_prefix=image.sha256[:12],
            readable=image.readable,
            error=image.error,
        )

    cache_key = build_cache_key(
        provider=cfg.provider,
        model=cfg.model,
        prompt_version=_effective_prompt_version(cfg),
        row=row,
        user_history=history,
        evidence_requirements=requirements,
        image_hashes=[image.sha256 for image in prepared_images],
        normalizer_version=NORMALIZER_VERSION,
    )
    cached = read_cache(paths.cache_dir, cache_key)
    if cached:
        if _cache_payload_is_trustworthy(cached):
            raw_json = cached.get("raw_json")
            if not isinstance(raw_json, dict):
                raw_json = {"decision": {}}
            result = ProviderResult(
                raw_json=raw_json,
                metadata=_metadata_from_cache(cached),
                used_fallback=False,
            )
            cache_hit = True
            final_provider = result.metadata.provider
        else:
            logger.write("cache_ignored_degraded_result", row_index=row_index, provider=cfg.provider)
            cached = None
    if not cached:
        result, primary_provider, final_provider, backup_used, backup_reason = _call_provider_chain(
            cfg,
            context,
            logger,
            provider_limiter=provider_limiter,
            backup_semaphore=backup_semaphore,
        )
        if not backup_used and not result.used_fallback and not result.metadata.error_category:
            write_cache(
                paths.cache_dir,
                cache_key,
                {
                    "raw_json": result.raw_json,
                    "metadata": result.metadata.__dict__,
                    "used_fallback": result.used_fallback,
                },
            )

    _write_provider_response_log(logger, context, result, cache_hit)
    final_row, repairs = normalize_provider_result(context, result)
    for repair in repairs:
        logger.write("normalization_repair", row_index=row_index, **repair)
    logger.write(
        "claim_completed",
        row_index=row_index,
        primary_provider=primary_provider,
        final_provider=final_provider or result.metadata.provider,
        backup_used=backup_used,
        backup_reason=backup_reason,
        claim_status=final_row["claim_status"],
        issue_type=final_row["issue_type"],
        object_part=final_row["object_part"],
        risk_flags=final_row["risk_flags"].split(";"),
        valid_image=final_row["valid_image"] == "true",
        evidence_standard_met=final_row["evidence_standard_met"] == "true",
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.write(
        "worker_claim_completed",
        row_index=row_index,
        worker_name=worker_name,
        thread_id=threading.get_ident(),
        duration_ms=duration_ms,
        backup_used=backup_used,
        used_fallback=result.used_fallback,
        cache_hit=cache_hit,
    )
    provider_calls = 0 if cache_hit or result.used_fallback else 1
    return RowResult(
        row_index=row_index,
        output_row=final_row,
        provider_calls=provider_calls,
        backup_used=backup_used,
        used_fallback=result.used_fallback,
        duration_ms=duration_ms,
        cache_hit=cache_hit,
    )


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def run_predictions(
    cfg: AppConfig,
    claims_csv: Path | None = None,
    output_csv: Path | None = None,
) -> list[dict[str, str]]:
    paths = cfg.paths
    if paths is None:
        raise ValueError("AppConfig.paths is required")

    claims_path = claims_csv or paths.claims_csv
    output_path = output_csv or paths.output_csv
    logger = JsonlLogger(paths.logs_dir / "run.jsonl")
    provider_name = cfg.provider

    claim_rows = load_claim_rows(claims_path)
    user_history = load_user_history(paths.user_history_csv)
    all_requirements = load_evidence_requirements(paths.evidence_requirements_csv)
    started = time.monotonic()

    logger.write(
        "run_started",
        provider=provider_name,
        model=cfg.model,
        claims_file=str(claims_path),
        output_file=str(output_path),
        fallback_allowed=cfg.allow_no_vision_fallback,
        prompt_cache_enabled=cfg.prompt_cache_enabled,
        prompt_cache_retention=cfg.prompt_cache_retention,
        output_limit=cfg.max_output_tokens,
        retry_max_sleep_seconds=cfg.retry_max_sleep_seconds,
        reasoning_enabled=cfg.reasoning_enabled,
        reasoning_effort=cfg.reasoning_effort,
        reasoning_max_tokens=cfg.reasoning_max_tokens,
        reasoning_exclude=cfg.reasoning_exclude,
        max_concurrency=cfg.max_concurrency,
        requests_per_minute=cfg.requests_per_minute,
        backup_max_concurrency=cfg.backup_max_concurrency,
    )

    provider_limiter = ProviderLimiter(cfg.requests_per_minute)
    backup_semaphore = threading.BoundedSemaphore(max(1, cfg.backup_max_concurrency))
    worker_count = max(1, cfg.max_concurrency)
    if worker_count <= 1:
        results = [
            process_claim_row(
                cfg=cfg,
                row_index=row_index,
                row=row,
                user_history=user_history,
                all_requirements=all_requirements,
                logger=logger,
                paths=paths,
                provider_limiter=provider_limiter,
                backup_semaphore=backup_semaphore,
            )
            for row_index, row in enumerate(claim_rows, start=1)
        ]
    else:
        results = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    process_claim_row,
                    cfg=cfg,
                    row_index=row_index,
                    row=row,
                    user_history=user_history,
                    all_requirements=all_requirements,
                    logger=logger,
                    paths=paths,
                    provider_limiter=provider_limiter,
                    backup_semaphore=backup_semaphore,
                )
                for row_index, row in enumerate(claim_rows, start=1)
            ]
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda result: result.row_index)
    output_rows = [result.output_row for result in results]
    write_output_rows(output_path, output_rows)
    durations = [result.duration_ms for result in results]
    logger.write(
        "run_completed",
        rows_processed=len(output_rows),
        output_file=str(output_path),
        max_concurrency=worker_count,
        provider_calls=sum(result.provider_calls for result in results),
        backup_provider_calls=sum(1 for result in results if result.backup_used),
        fallback_rows=sum(1 for result in results if result.used_fallback),
        cache_hits=sum(1 for result in results if result.cache_hit),
        cache_misses=sum(1 for result in results if not result.cache_hit),
        total_duration_ms=int((time.monotonic() - started) * 1000),
        average_claim_duration_ms=int(sum(durations) / len(durations)) if durations else 0,
        p50_claim_duration_ms=sorted(durations)[len(durations) // 2] if durations else 0,
        p95_claim_duration_ms=_p95(durations),
    )
    return output_rows
