"""Profiler tests: type inference, missing/dupes/outliers, encodings, edge cases."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from api.services.profiler import (
    ProfilingError, load_dataframe, profile_dataframe, profile_file,
)


def _profile(df: pd.DataFrame):
    return profile_dataframe(df, filename="t.csv", file_size=123)


def test_basic_counts_and_types():
    df = pd.DataFrame({
        "amount": [10.5, 20.0, None, 40.0],
        "category": ["a", "b", "a", "a"],
        "when": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
    })
    p = _profile(df)
    assert p.n_rows == 4 and p.n_cols == 3
    by_name = {c.name: c for c in p.columns}
    assert by_name["amount"].semantic_type == "numeric"
    assert by_name["amount"].missing_count == 1
    assert by_name["amount"].missing_pct == 25.0
    assert by_name["category"].semantic_type == "categorical"
    assert by_name["when"].semantic_type == "datetime"
    assert "when" in p.candidate_time_columns


def test_duplicates_and_outliers():
    base = pd.DataFrame({"x": [1.0, 2, 3, 4, 5, 6, 7, 8, 1000]})
    p = _profile(base)
    assert {c.name: c for c in p.columns}["x"].outlier_count_iqr == 1
    dup = pd.concat([base, base.iloc[[0]]], ignore_index=True)
    assert _profile(dup).duplicate_rows == 1


def test_string_dates_detected():
    df = pd.DataFrame({"d": ["2024-01-01", "2024-02-01", "2024-03-01"] * 10})
    p = _profile(df)
    assert {c.name: c for c in p.columns}["d"].semantic_type == "datetime"


def test_id_column_detected():
    df = pd.DataFrame({"order_id": range(1, 101), "v": [1.5] * 100})
    p = _profile(df)
    assert {c.name: c for c in p.columns}["order_id"].semantic_type == "id"


def test_warnings_for_edge_cases():
    df = pd.DataFrame({"only": [None] * 5})
    p = _profile(df)
    assert any("entirely null" in w for w in p.warnings)
    assert any("single-column" in w for w in p.warnings)


def test_arabic_columns_and_cp1256_encoding(tmp_path):
    csv = "الاسم,المبيعات\nأحمد,100\nليلى,250\n"
    path = tmp_path / "ar.csv"
    path.write_bytes(csv.encode("windows-1256"))
    df, encoding, _ = load_dataframe(path)
    assert "المبيعات" in df.columns
    p = profile_file(path)
    assert p.n_rows == 2
    assert {c.name for c in p.columns} == {"الاسم", "المبيعات"}


def test_utf8_roundtrip(tmp_path):
    path = tmp_path / "u.csv"
    path.write_text("name,qty\nfoo,1\nbar,2\n", encoding="utf-8")
    p = profile_file(path)
    assert p.n_rows == 2 and p.n_cols == 2


def test_xlsx_with_extra_sheets(tmp_path):
    path = tmp_path / "m.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="first", index=False)
        pd.DataFrame({"b": [3]}).to_excel(writer, sheet_name="second", index=False)
    p = profile_file(path)
    assert p.n_rows == 2
    assert p.extra_sheets == ["second"]


def test_row_limit_enforced(tmp_path):
    path = tmp_path / "big.csv"
    pd.DataFrame({"x": np.arange(100)}).to_csv(path, index=False)
    with pytest.raises(ProfilingError, match="limit"):
        load_dataframe(path, max_rows=50)


def test_unsupported_extension(tmp_path):
    path = tmp_path / "x.parquet"
    path.write_bytes(b"junk")
    with pytest.raises(ProfilingError, match="unsupported"):
        load_dataframe(path)
