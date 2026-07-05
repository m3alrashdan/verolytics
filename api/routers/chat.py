"""POST /chat — follow-up Q&A through the same agent loop."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import db
from api.models.session import SessionStatus
from api.routers.auth import ensure_session_access, optional_user
from api.services.agent import AnalystAgent

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str
    question: str
    language: str | None = None


@router.post("/chat")
async def chat(req: ChatRequest, user: dict | None = Depends(optional_user)) -> dict:
    ensure_session_access(req.session_id, user)
    state = db.load_state(req.session_id)
    if state is None:
        raise HTTPException(404, "unknown session_id")
    if state.status != SessionStatus.DONE:
        raise HTTPException(409, "ask follow-up questions after the analysis completes")
    if not req.question.strip():
        raise HTTPException(400, "question is empty")
    if req.language:
        state.language = req.language

    agent = AnalystAgent()
    try:
        result = await asyncio.to_thread(agent.answer_question, state, req.question.strip())
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat failed for session %s", req.session_id)
        raise HTTPException(500, f"could not answer the question: {exc}") from exc
    return {"session_id": req.session_id, **result}
