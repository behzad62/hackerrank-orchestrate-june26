from __future__ import annotations

from config import AppConfig, build_common_arg_parser, load_env_file
from runner import run_predictions


def main() -> int:
    parser = build_common_arg_parser("Run claim verification predictions.")
    args = parser.parse_args()
    load_env_file(args.env)
    cfg = AppConfig.from_env().with_overrides(
        claims=args.claims,
        history=args.history,
        evidence=args.evidence,
        images=args.images,
        output=args.output,
        log=args.log,
        cache=args.cache,
        provider=args.provider,
        model=args.model,
        retries=args.retries,
        fallback=args.fallback,
        max_concurrency=args.max_concurrency,
        requests_per_minute=args.requests_per_minute,
        backup_max_concurrency=args.backup_max_concurrency,
        prompt_cache_enabled=args.prompt_cache_enabled,
        prompt_cache_retention=args.prompt_cache_retention,
        strategy_mode=args.strategy_mode,
        adjudicator_provider=args.adjudicator_provider,
        adjudicator_model=args.adjudicator_model,
        ignore_cache=args.ignore_cache,
        cache_write_enabled=args.cache_write_enabled,
    )
    if cfg.paths is None:
        raise ValueError("AppConfig.paths is required")
    run_predictions(cfg, claims_csv=cfg.paths.claims_csv, output_csv=cfg.paths.output_csv)
    print(f"Wrote predictions to {cfg.paths.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
