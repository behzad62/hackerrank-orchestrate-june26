from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from cache import build_cache_key, read_cache, write_cache
from config import AppConfig
from data import load_claim_rows, load_evidence_requirements, load_user_history, write_output_rows
from images import prepare_images
from logging_config import JsonlLogger
from normalization import normalize_provider_result
from providers import AnthropicProvider, FallbackProvider, OpenAICompatibleProvider
from schemas import PredictionContext, ProviderMetadata, ProviderResult
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


def build_provider(cfg: AppConfig):
    provider = cfg.provider.strip().lower()
    if provider == "none":
        return FallbackProvider()
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            if cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("OPENAI_API_KEY is required when VLM_PROVIDER=openai")
        return OpenAICompatibleProvider(
            provider="openai",
            api_key=key,
            model=cfg.model,
            base_url="https://api.openai.com/v1",
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
        )
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            if cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("OPENROUTER_API_KEY is required when VLM_PROVIDER=openrouter")
        return OpenAICompatibleProvider(
            provider="openrouter",
            api_key=key,
            model=cfg.model,
            base_url="https://openrouter.ai/api/v1",
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
        )
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            if cfg.allow_no_vision_fallback:
                return FallbackProvider()
            raise RuntimeError("ANTHROPIC_API_KEY is required when VLM_PROVIDER=anthropic")
        return AnthropicProvider(
            api_key=key,
            model=cfg.model,
            temperature=cfg.temperature,
            timeout_seconds=cfg.timeout_seconds,
            max_output_tokens=cfg.max_output_tokens,
        )
    raise ValueError(f"Unsupported provider: {cfg.provider}")


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


def _sleep_seconds(attempt: int) -> int:
    return min(8, 2**attempt)


def _call_with_retries(provider: Any, context: PredictionContext, cfg: AppConfig, logger: JsonlLogger) -> ProviderResult:
    provider_name = getattr(provider, "name", cfg.provider)
    last_result: ProviderResult | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
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
        sleep_seconds = _sleep_seconds(attempt)
        logger.write(
            "provider_retry_scheduled",
            row_index=context.row_index,
            provider=provider_name,
            error_category=category,
            retry_count=attempt + 1,
            sleep_seconds=sleep_seconds,
        )
        time.sleep(sleep_seconds)

    if cfg.allow_no_vision_fallback:
        category = last_result.metadata.error_category if last_result else "unknown_provider_error"
        logger.write(
            "provider_fallback_used",
            row_index=context.row_index,
            provider=provider_name,
            error_category=category,
        )
        return _fallback_result(context, provider_name, category)

    category = last_result.metadata.error_category if last_result else "unknown_provider_error"
    raise RuntimeError(f"Provider failed and fallback is disabled: {category}")


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
        cache_hit=cache_hit,
        used_fallback=result.used_fallback,
    )


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
    provider = build_provider(cfg)
    provider_name = getattr(provider, "name", cfg.provider)

    claim_rows = load_claim_rows(claims_path)
    user_history = load_user_history(paths.user_history_csv)
    all_requirements = load_evidence_requirements(paths.evidence_requirements_csv)
    output_rows: list[dict[str, str]] = []

    logger.write(
        "run_started",
        provider=provider_name,
        model=cfg.model,
        claims_file=str(claims_path),
        output_file=str(output_path),
        fallback_allowed=cfg.allow_no_vision_fallback,
    )

    for row_index, row in enumerate(claim_rows, start=1):
        prepared_images = prepare_images(paths.repo_root, row.get("image_paths", ""), paths.images_dir)
        history = user_history.get(row.get("user_id", ""), {})
        requirements = _selected_requirements(all_requirements, row.get("claim_object", ""))
        context = PredictionContext(
            row_index=row_index,
            row=row,
            user_history=history,
            evidence_requirements=requirements,
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
            provider=provider_name,
            model=cfg.model,
            prompt_version=cfg.prompt_version,
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
            else:
                logger.write("cache_ignored_degraded_result", row_index=row_index, provider=provider_name)
                cached = None
        if not cached:
            result = _call_with_retries(provider, context, cfg, logger)
            if not result.used_fallback and not result.metadata.error_category:
                write_cache(
                    paths.cache_dir,
                    cache_key,
                    {
                        "raw_json": result.raw_json,
                        "metadata": result.metadata.__dict__,
                        "used_fallback": result.used_fallback,
                    },
                )
            cache_hit = False

        _write_provider_response_log(logger, context, result, cache_hit)
        final_row, repairs = normalize_provider_result(context, result)
        output_rows.append(final_row)

        for repair in repairs:
            logger.write("normalization_repair", row_index=row_index, **repair)
        logger.write(
            "claim_completed",
            row_index=row_index,
            claim_status=final_row["claim_status"],
            issue_type=final_row["issue_type"],
            object_part=final_row["object_part"],
            risk_flags=final_row["risk_flags"].split(";"),
            valid_image=final_row["valid_image"] == "true",
            evidence_standard_met=final_row["evidence_standard_met"] == "true",
        )

    write_output_rows(output_path, output_rows)
    logger.write("run_completed", rows_processed=len(output_rows), output_file=str(output_path))
    return output_rows
