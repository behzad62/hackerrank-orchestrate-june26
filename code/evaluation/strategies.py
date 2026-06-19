from __future__ import annotations

import re
from dataclasses import dataclass

from config import ProviderSpec, parse_provider_spec


VALID_STRATEGY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class EvalStrategy:
    name: str
    provider: str
    model: str
    mode: str = "one_pass"
    adjudicator_provider: str | None = None
    adjudicator_model: str | None = None
    prompt_version: str | None = None
    reasoning_enabled: bool | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    prompt_cache_enabled: bool | None = None


def _coerce_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean strategy option: {raw!r}")


def _validate_name(name: str) -> str:
    normalized = name.strip()
    if not VALID_STRATEGY_NAME.fullmatch(normalized):
        raise ValueError(f"Invalid strategy name: {name!r}")
    return normalized


def _validate_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in {"one_pass", "two_pass"}:
        raise ValueError(f"Invalid strategy mode: {mode!r}")
    return normalized


def parse_strategy(raw: str) -> EvalStrategy:
    name, separator, remainder = raw.strip().partition("=")
    if not separator:
        raise ValueError(f"Invalid strategy entry: {raw!r}")
    spec_text, *option_parts = [part.strip() for part in remainder.split(",") if part.strip()]
    spec = parse_provider_spec(spec_text)
    options: dict[str, str] = {}
    for option in option_parts:
        key, option_separator, value = option.partition("=")
        if not option_separator:
            raise ValueError(f"Invalid strategy option: {option!r}")
        options[key.strip().lower().replace("-", "_")] = value.strip()
    adjudicator_provider = None
    adjudicator_model = None
    if options.get("adjudicator"):
        adjudicator = parse_provider_spec(options["adjudicator"])
        adjudicator_provider = adjudicator.provider
        adjudicator_model = adjudicator.model
    return EvalStrategy(
        name=_validate_name(name),
        provider=spec.provider,
        model=spec.model,
        mode=_validate_mode(options.get("mode", "one_pass")),
        adjudicator_provider=adjudicator_provider,
        adjudicator_model=adjudicator_model,
        prompt_version=options.get("prompt_version"),
        reasoning_enabled=(
            _coerce_bool(options["reasoning_enabled"])
            if "reasoning_enabled" in options
            else None
        ),
        reasoning_effort=options.get("reasoning_effort"),
        max_output_tokens=(
            int(options["max_output_tokens"])
            if "max_output_tokens" in options
            else None
        ),
        prompt_cache_enabled=(
            _coerce_bool(options["prompt_cache_enabled"])
            if "prompt_cache_enabled" in options
            else None
        ),
    )


def parse_strategies(raw_values: list[str] | tuple[str, ...] | None, env_value: str = "") -> list[EvalStrategy]:
    entries: list[str] = []
    if env_value.strip():
        entries.extend(part.strip() for part in env_value.split(";") if part.strip())
    if raw_values:
        entries.extend(part.strip() for part in raw_values if part.strip())
    strategies = [parse_strategy(entry) for entry in entries]
    seen: set[str] = set()
    for strategy in strategies:
        lowered = strategy.name.lower()
        if lowered in seen:
            raise ValueError(f"Duplicate strategy name: {strategy.name}")
        seen.add(lowered)
    return strategies


def default_strategies(provider: str, model: str) -> list[EvalStrategy]:
    configured_model = model if provider != "none" else "none"
    return [
        EvalStrategy(name="configured", provider=provider.strip().lower(), model=configured_model),
        EvalStrategy(name="none-fallback", provider="none", model="none"),
    ]


def strategy_provider_spec(strategy: EvalStrategy) -> ProviderSpec:
    return ProviderSpec(provider=strategy.provider, model=strategy.model)
