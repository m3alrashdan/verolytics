"""Advanced tooling endpoints: what-if scenarios, NL transforms, cross-file joins,
executive presentations."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from api import db
from api.models.session import SessionStatus
from api.routers.auth import ensure_session_access, optional_user
from api.services.agent import AnalystAgent
from api.services.joins import execute_join, suggest_joins
from api.services.presentation import render_pptx, render_slides_html
from api.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tools"])


def _done_state(session_id: str):
    state = db.load_state(session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id")
    if state.status != SessionStatus.DONE:
        raise HTTPException(409, "run the analysis first")
    return state


# ------------------------------------------------------------- scenarios ----

class ScenarioRequest(BaseModel):
    description: str


@router.post("/sessions/{session_id}/scenario")
async def scenario(session_id: str, req: ScenarioRequest) -> dict:
    state = _done_state(session_id)
    if not req.description.strip():
        raise HTTPException(400, "scenario description is empty")
    agent = AnalystAgent()
    try:
        return await asyncio.to_thread(agent.run_scenario, state, req.description.strip())
    except Exception as exc:  # noqa: BLE001
        logger.exception("scenario failed for %s", session_id)
        raise HTTPException(500, f"scenario simulation failed: {exc}") from exc


# ------------------------------------------------------------ prediction ----

class PredictRequest(BaseModel):
    target: str | None = None
    horizon: int | None = None
    frequency: str | None = None
    model: str | None = None


@router.get("/sessions/{session_id}/columns")
async def columns(session_id: str, user: dict | None = Depends(optional_user)) -> dict:
    """Columns of the dataset, for the prediction target picker."""
    ensure_session_access(session_id, user)
    state = db.load_state(session_id)
    if state is None or state.profile is None:
        raise HTTPException(404, "unknown session_id")
    numeric_types = {"numeric", "integer", "float"}
    cols = [{"name": c.name, "semantic_type": c.semantic_type,
             "numeric": c.semantic_type in numeric_types} for c in state.profile.columns]
    return {"columns": cols, "numeric": [c["name"] for c in cols if c["numeric"]]}


@router.post("/sessions/{session_id}/predict")
async def predict(session_id: str, req: PredictRequest,
                  user: dict | None = Depends(optional_user)) -> dict:
    ensure_session_access(session_id, user)
    state = _done_state(session_id)
    agent = AnalystAgent()
    try:
        return await asyncio.to_thread(
            agent.run_prediction, state, req.target, req.horizon, req.frequency, req.model)
    except Exception as exc:  # noqa: BLE001
        logger.exception("prediction failed for %s", session_id)
        raise HTTPException(500, f"prediction failed: {exc}") from exc


# ------------------------------------------------------------ transforms ----

class TransformRequest(BaseModel):
    instruction: str


@router.post("/sessions/{session_id}/transform")
async def transform_preview(session_id: str, req: TransformRequest) -> dict:
    state = _done_state(session_id)
    if not req.instruction.strip():
        raise HTTPException(400, "instruction is empty")
    agent = AnalystAgent()
    try:
        return await asyncio.to_thread(agent.preview_transform, state, req.instruction.strip())
    except Exception as exc:  # noqa: BLE001
        logger.exception("transform failed for %s", session_id)
        raise HTTPException(500, f"transformation failed: {exc}") from exc


@router.post("/sessions/{session_id}/transform/apply")
async def transform_apply(session_id: str) -> dict:
    state = _done_state(session_id)
    ws = SandboxExecutor().workspace(session_id)
    transformed = ws / "data" / "transformed.parquet"
    cleaned = ws / "data" / "cleaned.parquet"
    if not transformed.exists():
        raise HTTPException(404, "no pending transformation — preview one first")
    if cleaned.exists():
        shutil.copy(cleaned, ws / "data" / "cleaned.backup.parquet")
    transformed.replace(cleaned)
    state.cleaning_log.append({
        "action": "user_transformation", "column": None,
        "before_count": None, "after_count": None,
        "justification": "applied a user-requested natural-language transformation",
    })
    db.save_state(state)
    return {"applied": True}


# ----------------------------------------------------------- cross-file ----

@router.post("/sessions/{session_id}/files")
async def add_file(session_id: str, file: UploadFile = File(...)) -> dict:
    """Attach a second file to the session for cross-file analysis."""
    state = db.load_state(session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id")
    suffix = Path(file.filename or "extra").suffix.lower()
    if suffix not in (".csv", ".xlsx", ".xls"):
        raise HTTPException(400, "upload a .csv or .xlsx file")
    payload = await file.read()
    ws = SandboxExecutor().workspace(session_id)
    extra = ws / "data" / f"extra{suffix}"
    extra.write_bytes(payload)
    try:
        candidates = await asyncio.to_thread(
            suggest_joins, _primary_data_path(ws), extra)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"could not read the file: {exc}") from exc
    return {"filename": file.filename, "join_candidates": candidates}


class JoinRequest(BaseModel):
    left_column: str
    right_column: str
    how: str = "left"


@router.post("/sessions/{session_id}/joins/apply")
async def apply_join(session_id: str, req: JoinRequest) -> dict:
    state = db.load_state(session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id")
    ws = SandboxExecutor().workspace(session_id)
    extra = next((p for p in (ws / "data").glob("extra.*")), None)
    if extra is None:
        raise HTTPException(404, "no second file attached")
    try:
        info = await asyncio.to_thread(
            execute_join, _primary_data_path(ws), extra,
            req.left_column, req.right_column, req.how, ws / "data" / "cleaned.parquet")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    state.cleaning_log.append({
        "action": "cross_file_join", "column": f"{req.left_column} = {req.right_column}",
        "before_count": info["left_rows"], "after_count": info["rows"],
        "justification": f"user-confirmed {req.how} join with the attached file",
    })
    db.save_state(state)
    return info


def _primary_data_path(ws: Path) -> Path:
    cleaned = ws / "data" / "cleaned.parquet"
    if cleaned.exists():
        return cleaned
    raw = next((p for p in (ws / "data").glob("raw.*")), None)
    if raw is None:
        raise HTTPException(404, "session has no data")
    return raw


# ---------------------------------------------------------- presentation ----

@router.get("/sessions/{session_id}/presentation/pptx")
async def presentation_pptx(session_id: str) -> Response:
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    ws = SandboxExecutor().workspace(session_id)
    try:
        pptx = await asyncio.to_thread(render_pptx, report, ws)
    except Exception as exc:  # noqa: BLE001
        logger.exception("pptx failed for %s", session_id)
        raise HTTPException(500, f"presentation generation failed: {exc}") from exc
    return Response(
        content=pptx,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="deck-{session_id[:8]}.pptx"'},
    )


@router.get("/sessions/{session_id}/presentation/slides", response_class=HTMLResponse)
async def presentation_slides(session_id: str) -> HTMLResponse:
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    ws = SandboxExecutor().workspace(session_id)
    return HTMLResponse(render_slides_html(report, ws))
