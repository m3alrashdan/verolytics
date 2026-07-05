"""Data-quality scoring: deterministic, pandas-derived, no LLM involved."""
from __future__ import annotations

from typing import Any

from api.models.session import DataProfile


def quality_breakdown(profile: DataProfile, cleaning_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score 0-100 across completeness / uniqueness / consistency / validity."""
    n_cells = max(profile.n_rows * profile.n_cols, 1)
    missing_cells = sum(c.missing_count for c in profile.columns)
    completeness = 100.0 * (1 - missing_cells / n_cells)

    uniqueness = 100.0 * (1 - profile.duplicate_rows / max(profile.n_rows, 1))

    # consistency: share of columns with a confidently-typed semantic type
    typed = sum(1 for c in profile.columns if c.semantic_type != "text")
    consistency = 100.0 * typed / max(profile.n_cols, 1)

    # validity: share of numeric values that are not IQR outliers
    numeric_cols = [c for c in profile.columns if c.semantic_type == "numeric"]
    if numeric_cols:
        total_vals = sum(profile.n_rows - c.missing_count for c in numeric_cols)
        outliers = sum(c.outlier_count_iqr or 0 for c in numeric_cols)
        validity = 100.0 * (1 - outliers / max(total_vals, 1))
    else:
        validity = 100.0

    dims = {
        "completeness": round(completeness, 1),
        "uniqueness": round(uniqueness, 1),
        "consistency": round(consistency, 1),
        "validity": round(validity, 1),
    }
    return {
        "score": round(sum(dims.values()) / 4, 1),
        "dimensions": dims,
        "missing_cells": missing_cells,
        "duplicate_rows": profile.duplicate_rows,
        "cleaning_actions": len(cleaning_log or []),
        "warnings": profile.warnings,
    }
