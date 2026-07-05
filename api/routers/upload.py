"""POST /upload — ingest a file, profile it, create the session workspace."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api import db
from api.config import get_settings
from api.models.session import SessionState
from api.routers.auth import optional_user
from api.services.profiler import ProfilingError, profile_file
from api.services.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["upload"])

ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "datasets"
SAMPLES = {
    "ecommerce-sales": "01_clean_sales.csv",
    "arabic-sales": "03_arabic_columns.csv",
    "financial-report": "09_financial.csv",
    "hr-data": "10_hr.csv",
}


@router.get("/samples")
async def list_samples() -> list[dict]:
    """Curated sample datasets for first-time users."""
    out = []
    for key, fname in SAMPLES.items():
        p = SAMPLES_DIR / fname
        if p.exists():
            out.append({"id": key, "filename": fname, "size_bytes": p.stat().st_size})
    return out


@router.post("/samples/{sample_id}")
async def upload_sample(sample_id: str, user: dict | None = Depends(optional_user)) -> dict:
    p = SAMPLES_DIR / SAMPLES.get(sample_id, "")
    if sample_id not in SAMPLES or not p.exists():
        raise HTTPException(404, "unknown sample")
    return await _ingest(p.name, p.read_bytes(), user)


@router.post("/upload")
async def upload(file: UploadFile = File(...),
                 user: dict | None = Depends(optional_user)) -> dict:
    payload = await file.read()
    return await _ingest(file.filename or "upload.csv", payload, user)


async def _ingest(filename: str, payload: bytes, user: dict | None = None) -> dict:
    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"unsupported file type '{suffix}' — upload a .csv or .xlsx file")
    if len(payload) > settings.max_file_mb * 1024 * 1024:
        raise HTTPException(400, f"file is larger than the {settings.max_file_mb} MB limit")
    if not payload:
        raise HTTPException(400, "the uploaded file is empty")

    session_id = uuid.uuid4().hex
    sandbox = SandboxExecutor(settings)
    workspace = sandbox.create_workspace(session_id)
    raw_path = workspace / "data" / f"raw{suffix}"
    raw_path.write_bytes(payload)

    try:
        profile = profile_file(raw_path, max_rows=settings.max_rows)
    except ProfilingError as exc:
        sandbox.destroy_workspace(session_id)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — unreadable/corrupt file
        sandbox.destroy_workspace(session_id)
        logger.exception("profiling failed for %s", filename)
        raise HTTPException(400, f"could not read the file: {exc}") from exc

    profile.filename = filename or raw_path.name
    state = SessionState(session_id=session_id, filename=profile.filename, profile=profile)
    db.save_state(state)
    if user:
        db.set_session_owner(session_id, user["id"])
    logger.info("session %s created for %s (%d rows x %d cols, owner=%s)",
                session_id, profile.filename, profile.n_rows, profile.n_cols,
                user["id"] if user else "anonymous")
    return {"session_id": session_id, "profile": profile.model_dump()}
