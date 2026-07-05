"""Cross-file intelligence: detect joinable columns between datasets.

Pure pandas + difflib heuristics — no LLM and no sandbox needed (we only read
the files the user uploaded, we never execute generated code here).
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

import pandas as pd

from api.services.profiler import load_dataframe

MAX_VALUE_SAMPLE = 2000


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _value_overlap(a: pd.Series, b: pd.Series) -> float:
    """Jaccard-style overlap of distinct values (sampled)."""
    va = set(a.dropna().astype(str).unique()[:MAX_VALUE_SAMPLE])
    vb = set(b.dropna().astype(str).unique()[:MAX_VALUE_SAMPLE])
    if not va or not vb:
        return 0.0
    inter = len(va & vb)
    return inter / min(len(va), len(vb))


def suggest_joins(left_path: Path, right_path: Path) -> list[dict[str, Any]]:
    """Return join candidates between two files, sorted by confidence."""
    left, _, _ = load_dataframe(left_path)
    right, _, _ = load_dataframe(right_path)

    candidates: list[dict[str, Any]] = []
    for lc in left.columns:
        for rc in right.columns:
            name_sim = difflib.SequenceMatcher(None, _norm(str(lc)), _norm(str(rc))).ratio()
            overlap = _value_overlap(left[lc], right[rc])
            # require some evidence in either dimension
            if name_sim < 0.55 and overlap < 0.3:
                continue
            confidence = round(0.45 * name_sim + 0.55 * overlap, 3)
            if confidence < 0.35:
                continue
            candidates.append({
                "left_column": str(lc),
                "right_column": str(rc),
                "name_similarity": round(name_sim, 3),
                "value_overlap": round(overlap, 3),
                "confidence": confidence,
                "left_unique": int(left[lc].nunique(dropna=True)),
                "right_unique": int(right[rc].nunique(dropna=True)),
            })
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[:10]


def execute_join(left_path: Path, right_path: Path, left_on: str, right_on: str,
                 how: str, out_path: Path) -> dict[str, Any]:
    """Run the confirmed join and persist the merged dataset."""
    if how not in ("inner", "left", "right", "outer"):
        raise ValueError(f"unsupported join type: {how}")
    left, _, _ = load_dataframe(left_path)
    right, _, _ = load_dataframe(right_path)
    if left_on not in left.columns or right_on not in right.columns:
        raise ValueError("join column not found")
    merged = left.merge(right, left_on=left_on, right_on=right_on,
                        how=how, suffixes=("", "_right"))
    merged.to_parquet(out_path)
    return {"rows": int(len(merged)), "cols": int(merged.shape[1]),
            "left_rows": int(len(left)), "right_rows": int(len(right))}
