"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.config import get_settings
from api.middleware import install_middleware
from api.routers import analyze, auth, chat, dashboard, report, tools, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    db.init_db()
    recovered = db.recover_orphaned_jobs()
    if recovered:
        logger.warning("recovered %d orphaned session(s) left running by a previous shutdown",
                       recovered)
    logger.info("data-analyst-agent API ready (provider=%s, model=%s, sandbox=%s)",
                settings.llm_provider, settings.active_model, settings.sandbox_image)
    if not settings.credentials_present:
        logger.warning(
            "no API credentials found for provider '%s' — analysis calls will fail. "
            "Set the matching key (e.g. OPENROUTER_API_KEY) in your environment or .env.",
            settings.llm_provider,
        )
    yield


app = FastAPI(
    title="Data Analyst Agent",
    description="Autonomous data analysis with sandboxed code execution and a "
                "number-verification gate. The LLM never computes numbers.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# request IDs + access logging, security headers, and per-IP rate limiting
install_middleware(app, get_settings())

app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(chat.router)
app.include_router(report.router)
app.include_router(dashboard.router)
app.include_router(tools.router)


@app.get("/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "version": app.version,
        "provider": s.llm_provider,
        "model": s.active_model,
        "credentials_configured": s.credentials_present,
    }
