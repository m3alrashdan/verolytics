"""POST /analyze — run the agent pipeline in the background; GET status."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import db
from api.config import get_settings
from api.models.session import SessionState, SessionStatus
from api.routers.auth import ensure_session_access, optional_user
from api.services.agent import AnalystAgent
from api.services.report_generator import render_html
from api.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analyze"])

# The agent loop is synchronous (Docker SDK + LLM SDK); run it off the event loop.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")


class AnalyzeRequest(BaseModel):
    session_id: str
    goal: str | None = None
    language: str = "en"


def _run_pipeline(state: SessionState) -> None:
    settings = get_settings()
    try:
        agent = AnalystAgent(settings=settings)
        agent.sandbox.ensure_image()
        emit = lambda t, p: db.append_event(state.session_id, t, p)  # noqa: E731
        state, report = agent.run(state, on_progress=db.save_state, on_event=emit)
        workspace = agent.sandbox.workspace(state.session_id)
        html = render_html(report, workspace)
        db.save_report(report, html=html)
        db.save_state(state)
    except Exception as exc:  # noqa: BLE001 — surface failure to the client, never crash
        logger.exception("pipeline failed for session %s", state.session_id)
        state.status = SessionStatus.FAILED
        state.error = str(exc)
        state.progress_message = f"Analysis failed: {exc}"
        db.save_state(state)
        db.append_event(state.session_id, "analysis_failed", {"error": str(exc)})


@router.post("/analyze")
async def analyze(req: AnalyzeRequest, user: dict | None = Depends(optional_user)) -> dict:
    ensure_session_access(req.session_id, user)
    state = db.load_state(req.session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id — upload a file first")
    if state.status not in (SessionStatus.UPLOADED, SessionStatus.FAILED, SessionStatus.DONE):
        raise HTTPException(409, f"analysis already running (status={state.status.value})")
    if req.language not in ("en", "ar"):
        raise HTTPException(400, "language must be 'en' or 'ar'")

    state.goal = req.goal
    state.language = req.language
    state.status = SessionStatus.PLANNING
    state.progress = 0.01
    state.progress_message = "Queued"
    state.step_results = []
    state.cleaning_log = []
    state.error = None
    db.save_state(state)
    _executor.submit(_run_pipeline, state)
    return {"session_id": state.session_id, "status": state.status.value}


@router.get("/sessions")
async def list_sessions(limit: int = 20, user: dict | None = Depends(optional_user)) -> list[dict]:
    """Most recent sessions for the history panel.

    Scoped to the caller: a logged-in user sees only their own sessions; an
    anonymous caller sees only ownerless (anonymous) sessions.
    """
    from sqlalchemy import select

    owner_filter = user["id"] if user else None
    with db.db_session() as s:
        rows = s.execute(
            select(db.SessionRecord)
            .where(db.SessionRecord.owner_id == owner_filter)
            .order_by(db.SessionRecord.created_at.desc()).limit(limit)
        ).scalars().all()
        return [{"session_id": r.id, "filename": r.filename, "status": r.status,
                 "language": r.language, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/analyze/{session_id}/status")
async def status(session_id: str, user: dict | None = Depends(optional_user)) -> dict:
    ensure_session_access(session_id, user)
    state = db.load_state(session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id")
    return {
        "session_id": session_id,
        "status": state.status.value,
        "progress": state.progress,
        "message": state.progress_message,
        "error": state.error,
        "plan": state.plan.model_dump() if state.plan else None,
        "steps": [
            {"step_number": sr.step.step_number, "description": sr.step.description,
             "status": sr.status, "attempts": sr.attempts, "skip_reason": sr.skip_reason}
            for sr in state.step_results
        ],
    }
