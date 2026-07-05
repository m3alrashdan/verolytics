"""Platform/durability tests (Phase 3): orphaned-job recovery on startup."""
from __future__ import annotations

import pytest

from api.config import get_settings
from api.models.session import SessionState, SessionStatus


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the db layer at a throwaway sqlite file for the test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'platform.db'}")
    get_settings.cache_clear()
    from api import db
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    db._engine = None
    db._SessionLocal = None
    get_settings.cache_clear()


def test_recover_orphaned_jobs_fails_running_sessions(temp_db):
    db = temp_db
    db.save_state(SessionState(session_id="run1", filename="a.csv",
                               status=SessionStatus.ANALYZING, progress=0.5))
    db.save_state(SessionState(session_id="run2", filename="b.csv",
                               status=SessionStatus.PLANNING, progress=0.05))
    db.save_state(SessionState(session_id="done1", filename="c.csv",
                               status=SessionStatus.DONE, progress=1.0))

    recovered = db.recover_orphaned_jobs()
    assert recovered == 2

    for sid in ("run1", "run2"):
        s = db.load_state(sid)
        assert s.status == SessionStatus.FAILED
        assert "interrupted" in (s.error or "").lower()
    # a completed session is untouched
    assert db.load_state("done1").status == SessionStatus.DONE


def test_recover_is_idempotent(temp_db):
    db = temp_db
    db.save_state(SessionState(session_id="run1", filename="a.csv",
                               status=SessionStatus.VERIFYING, progress=0.9))
    assert db.recover_orphaned_jobs() == 1
    # nothing left running → a second pass recovers nothing
    assert db.recover_orphaned_jobs() == 0


def _mw_client(per_minute: int):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.config import Settings
    from api.middleware import install_middleware

    app = FastAPI()
    install_middleware(app, Settings(_env_file=None, rate_limit_per_minute=per_minute))

    @app.get("/ping")
    def ping():  # noqa: ANN202
        return {"ok": True}

    return TestClient(app)


def test_request_id_and_security_headers():
    r = _mw_client(0).get("/ping")  # 0 disables the limiter
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_rate_limit_returns_429_over_budget():
    client = _mw_client(3)
    statuses = [client.get("/ping").status_code for _ in range(6)]
    assert statuses[:3] == [200, 200, 200]
    assert 429 in statuses[3:]
    # the 429 carries a Retry-After
    limited = client.get("/ping")
    assert limited.status_code == 429 and limited.headers.get("Retry-After")
