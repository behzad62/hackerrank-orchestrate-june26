from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from schemas import OUTPUT_COLUMNS


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required CSV file not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_claim_rows(path: Path) -> list[dict[str, str]]:
    return _read_csv(path)


def load_user_history(path: Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(path)
    return {row["user_id"]: row for row in rows if row.get("user_id")}


def load_evidence_requirements(path: Path, claim_object: str | None = None) -> list[dict[str, str]]:
    rows = _read_csv(path)
    if claim_object is None:
        return rows
    return [
        row
        for row in rows
        if row.get("claim_object") in {"all", claim_object}
    ]


def write_output_rows(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})
