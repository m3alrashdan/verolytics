"""Dashboard endpoints: SSE live progress, KPI cards, quality, suggestions, chart JSON."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api import db
from api.models.session import SessionStatus
from api.services.quality import quality_breakdown
from api.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

SSE_POLL_S = 0.5
SSE_MAX_IDLE_S = 600
TERMINAL_EVENTS = {"analysis_complete", "analysis_failed"}


@router.get("/sessions/{session_id}/progress")
async def stream_progress(session_id: str) -> StreamingResponse:
    """Server-Sent Events stream of live analysis progress."""
    if db.load_state(session_id) is None:
        raise HTTPException(404, "unknown session_id")

    async def event_generator():
        last_seq = 0.0
        idle = 0.0
        # replay history first so reconnects don't lose events
        while True:
            events = await asyncio.to_thread(db.events_since, session_id, last_seq)
            for ev in events:
                last_seq = max(last_seq, ev["seq"])
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                if ev["type"] in TERMINAL_EVENTS:
                    return
            if events:
                idle = 0.0
            else:
                idle += SSE_POLL_S
                if idle >= SSE_MAX_IDLE_S:
                    return
                if idle and int(idle) % 15 == 0:
                    yield ": keep-alive\n\n"
            # stop streaming if the session already reached a terminal state
            state = await asyncio.to_thread(db.load_state, session_id)
            if state and state.status in (SessionStatus.DONE, SessionStatus.FAILED) and not events:
                yield (f"event: {'analysis_complete' if state.status == SessionStatus.DONE else 'analysis_failed'}"
                       f"\ndata: {json.dumps({'status': state.status.value, 'error': state.error})}\n\n")
                return
            await asyncio.sleep(SSE_POLL_S)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/sessions/{session_id}/kpis")
async def kpis(session_id: str) -> dict:
    report = db.load_report(session_id)
    if report is None:
        raise HTTPException(404, "no report for this session yet")
    return {"kpis": [k.model_dump() for k in report.kpis]}


@router.get("/sessions/{session_id}/quality")
async def quality(session_id: str) -> dict:
    state = db.load_state(session_id)
    if state is None or state.profile is None:
        raise HTTPException(404, "unknown session_id")
    return quality_breakdown(state.profile, state.cleaning_log)


@router.get("/sessions/{session_id}/charts/{chart_name}/json")
async def chart_json(session_id: str, chart_name: str) -> dict:
    """Plotly figure JSON for native interactive rendering in the web UI.

    Reads straight from the session workspace so charts are also available
    *during* the analysis (live previews), before any report exists.
    """
    if db.load_state(session_id) is None:
        raise HTTPException(404, "unknown session_id")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in chart_name)
    json_file = SandboxExecutor().workspace(session_id) / "charts" / f"{safe}.json"
    if not json_file.exists():
        raise HTTPException(404, "chart JSON not available")
    return json.loads(json_file.read_text(encoding="utf-8"))


@router.get("/sessions/{session_id}/suggestions")
async def suggestions(session_id: str) -> dict:
    """Suggested follow-up questions, contextual to the data (deterministic)."""
    state = db.load_state(session_id)
    if state is None or state.profile is None:
        raise HTTPException(404, "unknown session_id")
    p = state.profile
    lang = state.language
    numeric = [c.name for c in p.columns if c.semantic_type == "numeric"][:2]
    cats = [c.name for c in p.columns if c.semantic_type == "categorical"][:2]
    time_col = p.candidate_time_columns[0] if p.candidate_time_columns else None

    qs: list[str] = []
    if lang == "ar":
        if numeric and cats:
            qs.append(f"ما أعلى {cats[0]} من حيث {numeric[0]}؟")
        if time_col and numeric:
            qs.append(f"كيف تغيّر {numeric[0]} عبر الزمن؟")
        if numeric:
            qs.append(f"ما القيم الشاذة في {numeric[0]}؟")
        qs.append("ماذا لو ارتفعت الأسعار 10%؟")
    else:
        if numeric and cats:
            qs.append(f"Which {cats[0]} has the highest {numeric[0]}?")
        if time_col and numeric:
            qs.append(f"How did {numeric[0]} change over time?")
        if numeric:
            qs.append(f"Are there outliers in {numeric[0]}?")
        qs.append("What if prices increased by 10%?")
    return {"suggestions": qs[:4]}
