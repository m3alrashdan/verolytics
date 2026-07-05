"""Data profiling: load CSV/XLSX with encoding detection and build a DataProfile.

The profile (not the raw file) is what gets sent to the LLM, so it must be
compact but information-dense.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from api.models.session import ColumnProfile, DataProfile

logger = logging.getLogger(__name__)

SAMPLE_VALUES = 5
ID_UNIQUENESS_THRESHOLD = 0.98
CATEGORICAL_UNIQUE_RATIO = 0.5
TRY_ENCODINGS = ("utf-8", "utf-8-sig", "windows-1256", "iso-8859-1", "cp1252")


class ProfilingError(ValueError):
    """Raised for unreadable / unsupported / oversized files."""


def detect_encoding(path: Path) -> str:
    """Detect text encoding; prefers charset-normalizer, falls back to trial reads."""
    try:
        from charset_normalizer import from_path

        best = from_path(path).best()
        if best is not None and best.encoding:
            return best.encoding
    except Exception:  # noqa: BLE001 — fall back to trial decoding
        pass
    raw = path.read_bytes()[:262_144]
    for enc in TRY_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def load_dataframe(path: Path, max_rows: int | None = None) -> tuple[pd.DataFrame, str | None, list[str]]:
    """Load a CSV or XLSX file. Returns (df, encoding, extra_sheet_names)."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        xls = pd.ExcelFile(path)
        df = xls.parse(xls.sheet_names[0])
        extra = xls.sheet_names[1:]
        encoding = None
    elif suffix == ".csv":
        encoding = detect_encoding(path)
        try:
            df = pd.read_csv(path, encoding=encoding, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(path, encoding=encoding)
        extra = []
    else:
        raise ProfilingError(f"unsupported file type: {suffix} (only .csv and .xlsx are accepted)")

    if df.empty and df.shape[1] == 0:
        raise ProfilingError("the file contains no tabular data")
    if max_rows is not None and len(df) > max_rows:
        raise ProfilingError(f"file has {len(df):,} rows; the limit is {max_rows:,}")
    return df, encoding, [str(s) for s in extra]


def _semantic_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    non_null = series.dropna()
    n = len(non_null)
    if n == 0:
        return "text"
    if pd.api.types.is_numeric_dtype(series):
        # integer columns that are unique AND consecutive-like are identifiers,
        # not measurements (e.g. order_id 1..N); a unique measurement column
        # like [1, 2, ..., 1000] must stay numeric.
        if (
            non_null.nunique() / n > ID_UNIQUENESS_THRESHOLD
            and (non_null % 1 == 0).all()
            and n > 1
            and (non_null.max() - non_null.min()) <= 1.5 * n
        ):
            return "id"
        return "numeric"
    if _looks_like_datetime(non_null):
        return "datetime"
    ratio = non_null.nunique() / n
    if non_null.nunique() / max(n, 1) > ID_UNIQUENESS_THRESHOLD:
        return "id"
    if ratio <= CATEGORICAL_UNIQUE_RATIO:
        return "categorical"
    return "text"


def _looks_like_datetime(non_null: pd.Series) -> bool:
    sample = non_null.astype(str).head(50)
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed = pd.to_datetime(sample, errors="coerce", format="mixed", dayfirst=False)
        return parsed.notna().mean() > 0.9
    except Exception:  # noqa: BLE001
        return False


def _iqr_outliers(series: pd.Series) -> int:
    s = series.dropna()
    if len(s) < 4:
        return 0
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0
    return int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())


def _sample_values(series: pd.Series) -> list[Any]:
    vals = series.dropna().unique()[:SAMPLE_VALUES]
    out: list[Any] = []
    for v in vals:
        if isinstance(v, (pd.Timestamp,)):
            out.append(v.isoformat())
        elif hasattr(v, "item"):
            out.append(v.item())
        else:
            out.append(str(v)[:80])
    return out


def profile_dataframe(df: pd.DataFrame, *, filename: str, file_size: int,
                      encoding: str | None = None, extra_sheets: list[str] | None = None) -> DataProfile:
    """Compute the full data profile that seeds the agent's context."""
    columns: list[ColumnProfile] = []
    time_candidates: list[str] = []
    warnings_: list[str] = []

    n_rows = len(df)
    if n_rows == 0:
        warnings_.append("the file has headers but zero data rows")
    if df.shape[1] == 1:
        warnings_.append("single-column file — analysis options are limited")

    for col in df.columns:
        series = df[col]
        sem = _semantic_type(series)
        missing = int(series.isna().sum())
        stats: dict[str, Any] = {}
        outliers = None
        if sem == "numeric":
            s = series.dropna()
            if len(s):
                stats = {
                    "min": float(s.min()), "max": float(s.max()),
                    "mean": round(float(s.mean()), 4), "std": round(float(s.std()), 4) if len(s) > 1 else 0.0,
                    "median": float(s.median()),
                }
            outliers = _iqr_outliers(series)
        if sem == "datetime":
            time_candidates.append(str(col))
        if n_rows > 0 and missing == n_rows:
            warnings_.append(f"column '{col}' is entirely null")
        columns.append(ColumnProfile(
            name=str(col),
            dtype=str(series.dtype),
            semantic_type=sem,
            missing_count=missing,
            missing_pct=round(100.0 * missing / n_rows, 2) if n_rows else 0.0,
            n_unique=int(series.nunique(dropna=True)),
            sample_values=_sample_values(series),
            stats=stats,
            outlier_count_iqr=outliers,
        ))

    return DataProfile(
        filename=filename,
        file_size_bytes=file_size,
        encoding=encoding,
        n_rows=n_rows,
        n_cols=df.shape[1],
        duplicate_rows=int(df.duplicated().sum()),
        columns=columns,
        candidate_time_columns=time_candidates,
        warnings=warnings_,
        extra_sheets=extra_sheets or [],
    )


def profile_file(path: Path, max_rows: int | None = None) -> DataProfile:
    """Load and profile a file in one step."""
    df, encoding, extra = load_dataframe(path, max_rows=max_rows)
    return profile_dataframe(
        df, filename=path.name, file_size=path.stat().st_size,
        encoding=encoding, extra_sheets=extra,
    )
