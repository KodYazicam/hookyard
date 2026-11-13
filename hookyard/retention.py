from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from .persist import JsonFileStore

MAX_BINS_ENV = "HOOKYARD_MAX_BINS"
MAX_AGE_DAYS_ENV = "HOOKYARD_MAX_AGE_DAYS"


def _checked_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be >= 1")
    return value


def _checked_float(value: float, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError(f"{label} must be > 0")
    return float(value)


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    return _checked_int(value, name)


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number") from error
    return _checked_float(value, name)


def resolve_retention(
    max_bins: int | None = None,
    max_age_days: float | None = None,
) -> tuple[int | None, float | None]:
    resolved_bins = (
        _env_int(MAX_BINS_ENV)
        if max_bins is None
        else _checked_int(max_bins, "--max-bins")
    )
    resolved_age = (
        _env_float(MAX_AGE_DAYS_ENV)
        if max_age_days is None
        else _checked_float(max_age_days, "--max-age-days")
    )
    return resolved_bins, resolved_age


def describe_retention(
    max_bins: int | None, max_age_days: float | None
) -> str:
    limits: list[str] = []
    if max_bins is not None:
        limits.append(f"max {max_bins} bins")
    if max_age_days is not None:
        limits.append(f"max age {max_age_days:g} days")
    return ", ".join(limits)


def prune_data_file(
    data_file: str | Path,
    *,
    max_bins: int | None = None,
    max_age_days: float | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply retention to a data file, only writing when not a dry run."""
    path = Path(data_file)
    checked_bins = (
        None if max_bins is None else _checked_int(max_bins, "max_bins")
    )
    checked_age = (
        None
        if max_age_days is None
        else _checked_float(max_age_days, "max_age_days")
    )
    configured = checked_bins is not None or checked_age is not None

    removed: list[str] = []
    if path.exists():
        store = JsonFileStore(path)
        store.configure_retention(
            max_bins=checked_bins, max_age_days=checked_age
        )
        removed = (
            store.preview_prune() if dry_run else store.prune()
        )

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "configured": configured,
        "data_file": str(path),
        "max_bins": checked_bins,
        "max_age_days": checked_age,
        "removed": len(removed),
        "bins": removed,
    }
