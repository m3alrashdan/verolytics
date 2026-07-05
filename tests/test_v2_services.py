"""Tests for v2 services: quality scoring, join suggestion, presentation."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from api.models.report import ChartMeta, Finding, KPI, Report
from api.services.joins import execute_join, suggest_joins
from api.services.presentation import render_pptx, render_slides_html
from api.services.profiler import profile_dataframe
from api.services.quality import quality_breakdown


def test_quality_breakdown_clean_data():
    df = pd.DataFrame({"a": [1.0, 2, 3, 4], "b": ["x", "y", "x", "y"]})
    q = quality_breakdown(profile_dataframe(df, filename="t", file_size=1))
    assert q["score"] > 90
    assert q["dimensions"]["completeness"] == 100.0
    assert q["dimensions"]["uniqueness"] == 100.0


def test_quality_breakdown_dirty_data():
    df = pd.DataFrame({"a": [1.0, None, None, None], "b": ["x"] * 4})
    df = pd.concat([df, df], ignore_index=True)  # 100% duplicated
    q = quality_breakdown(profile_dataframe(df, filename="t", file_size=1))
    assert q["dimensions"]["completeness"] < 70
    assert q["dimensions"]["uniqueness"] < 60


def test_suggest_joins_finds_key(tmp_path: Path):
    left = tmp_path / "orders.csv"
    right = tmp_path / "customers.csv"
    pd.DataFrame({"customer_id": [1, 2, 3, 4], "amount": [10, 20, 30, 40]}).to_csv(left, index=False)
    pd.DataFrame({"CustomerID": [1, 2, 3, 9], "name": list("abcd")}).to_csv(right, index=False)
    cands = suggest_joins(left, right)
    assert cands, "expected at least one join candidate"
    best = cands[0]
    assert best["left_column"] == "customer_id" and best["right_column"] == "CustomerID"
    assert best["confidence"] > 0.5


def test_execute_join(tmp_path: Path):
    left = tmp_path / "l.csv"
    right = tmp_path / "r.csv"
    out = tmp_path / "merged.parquet"
    pd.DataFrame({"id": [1, 2], "v": [10, 20]}).to_csv(left, index=False)
    pd.DataFrame({"id": [1, 2], "w": [7, 8]}).to_csv(right, index=False)
    info = execute_join(left, right, "id", "id", "left", out)
    assert info["rows"] == 2
    assert set(pd.read_parquet(out).columns) >= {"id", "v", "w"}


def _report() -> Report:
    return Report(
        session_id="s", language="en", title="Deck test",
        executive_summary="Total revenue reached 1,234.",
        kpis=[KPI(label="Revenue", value="1,234", change="+5%", change_direction="up")],
        findings=[Finding(title="F1", narrative="Total was 1,234. It grew steadily.")],
        recommendations=["Do X.", "Do Y."],
        charts=[ChartMeta(name="c1", title="C1", html_path="charts/c1.html")],
        verification={"ok": True, "checked": 1, "matched": 1, "unmatched": [], "redacted": False},
    )


def test_pptx_renders(tmp_path: Path):
    data = render_pptx(_report(), tmp_path)
    assert data[:2] == b"PK" and len(data) > 10_000  # valid zip container


def test_reveal_slides_render(tmp_path: Path):
    html = render_slides_html(_report(), tmp_path)
    assert "reveal" in html and "Deck test" in html and 'dir="ltr"' in html
    ar = _report().model_copy(update={"language": "ar"})
    assert 'dir="rtl"' in render_slides_html(ar, tmp_path)
