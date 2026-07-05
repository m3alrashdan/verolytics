"""GET /report/{session_id} — interactive HTML; /pdf — downloadable PDF."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from api import db
from api.routers.auth import ensure_session_access, optional_user
from api.services.report_generator import render_pdf
from api.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["report"])


@router.get("/report/{session_id}", response_class=HTMLResponse)
async def report_html(session_id: str) -> HTMLResponse:
    # Opened via direct navigation / export links (no auth header possible), so
    # this stays URL-accessible by its unguessable id; the SPA's JSON view is guarded.
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    with db.db_session() as s:
        rec = s.get(db.ReportRecord, session_id)
        if rec is not None and rec.html:
            return HTMLResponse(rec.html)
    raise HTTPException(404, "report HTML not found")


@router.get("/report/{session_id}/json")
async def report_json(session_id: str, user: dict | None = Depends(optional_user)) -> dict:
    ensure_session_access(session_id, user)
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    return report.model_dump()


@router.get("/report/{session_id}/chart/{chart_name}", response_class=HTMLResponse)
async def report_chart(session_id: str, chart_name: str) -> HTMLResponse:
    """Serve one chart as a standalone interactive HTML page (for iframes)."""
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    chart = next((c for c in report.charts if c.name == chart_name), None)
    if chart is None:
        raise HTTPException(404, "unknown chart")
    workspace = SandboxExecutor().workspace(session_id)
    html_file = workspace / chart.html_path
    if not html_file.exists():
        raise HTTPException(404, "chart artifact expired")
    snippet = html_file.read_text(encoding="utf-8")
    return HTMLResponse(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
        "<style>body{margin:0;background:#fff}</style></head>"
        f"<body>{snippet}</body></html>"
    )


@router.get("/data/{session_id}/cleaned.csv")
async def cleaned_csv(session_id: str) -> Response:
    """Download the cleaned dataset produced by the cleaning step."""
    workspace = SandboxExecutor().workspace(session_id)
    parquet = workspace / "data" / "cleaned.parquet"
    if not parquet.exists():
        raise HTTPException(404, "no cleaned dataset for this session")
    import pandas as pd

    csv = pd.read_parquet(parquet).to_csv(index=False)
    return Response(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="cleaned-{session_id[:8]}.csv"'},
    )


@router.get("/report/{session_id}/pdf")
async def report_pdf(session_id: str) -> Response:
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    workspace = SandboxExecutor().workspace(session_id)
    try:
        pdf = render_pdf(report, workspace)
    except Exception as exc:  # noqa: BLE001 — e.g. WeasyPrint native deps missing
        logger.exception("pdf rendering failed for %s", session_id)
        raise HTTPException(500, f"PDF rendering failed: {exc}") from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{session_id[:8]}.pdf"'},
    )
