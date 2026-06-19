from __future__ import annotations

from config import AppConfig, build_common_arg_parser
from runner import run_predictions


def main() -> int:
    parser = build_common_arg_parser("Run claim verification predictions.")
    args = parser.parse_args()
    cfg = AppConfig.from_env().with_overrides(
        claims=args.claims,
        output=args.output,
        provider=args.provider,
        model=args.model,
    )
    if cfg.paths is None:
        raise ValueError("AppConfig.paths is required")
    run_predictions(cfg, claims_csv=cfg.paths.claims_csv, output_csv=cfg.paths.output_csv)
    print(f"Wrote predictions to {cfg.paths.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
