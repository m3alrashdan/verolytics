"""Auth tests (Phase 3d): password hashing + register/login/me/logout flow."""
from __future__ import annotations

import pytest

from api.config import get_settings
from api.models.session import SessionState, SessionStatus
from api.services.auth import hash_password, verify_password


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    get_settings.cache_clear()
    from api import db
    db._engine = None
    db._SessionLocal = None
    db.init_db()
    yield db
    db._engine = None
    db._SessionLocal = None
    get_settings.cache_clear()


def test_password_hash_roundtrip_and_uniqueness():
    h = hash_password("hunter2pass")
    assert h != "hunter2pass" and h.startswith("pbkdf2_sha256$")
    assert verify_password("hunter2pass", h)
    assert not verify_password("wrong", h)
    # same password hashes differently (random salt)
    assert hash_password("hunter2pass") != h


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import auth
    app = FastAPI()
    app.include_router(auth.router)
    return TestClient(app)


def test_register_login_me_logout(temp_db):
    client = _client()
    creds = {"email": "Jane@Example.com", "password": "supersecret1"}

    r = client.post("/auth/register", json=creds)
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["user"]["email"] == "jane@example.com"  # normalised

    # duplicate email (case-insensitive) is rejected
    assert client.post("/auth/register", json={**creds, "email": "jane@example.com"}).status_code == 409
    # weak password rejected
    assert client.post("/auth/register",
                       json={"email": "x@y.com", "password": "short"}).status_code == 400

    # wrong password / unknown user → 401
    assert client.post("/auth/login", json={**creds, "password": "nope"}).status_code == 401
    assert client.post("/auth/login",
                       json={"email": "ghost@y.com", "password": "whatever1"}).status_code == 401

    # correct login issues a token
    assert client.post("/auth/login", json=creds).status_code == 200

    auth_h = {"Authorization": f"Bearer {token}"}
    me = client.get("/auth/me", headers=auth_h)
    assert me.status_code == 200 and me.json()["email"] == "jane@example.com"
    assert "password_hash" not in me.json()  # never leak the hash

    # no/!bad token → 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401

    # logout revokes the token
    assert client.post("/auth/logout", headers=auth_h).status_code == 200
    assert client.get("/auth/me", headers=auth_h).status_code == 401


def test_session_ownership_and_isolation(temp_db):
    import pytest
    from fastapi import HTTPException
    from api.routers.auth import ensure_session_access

    db = temp_db
    # anonymous (ownerless) session is accessible to anyone
    db.save_state(SessionState(session_id="anon", filename="a.csv"))
    ensure_session_access("anon", None)
    ensure_session_access("anon", {"id": "u1"})

    # owned session is private to its owner
    db.save_state(SessionState(session_id="owned", filename="b.csv"))
    db.set_session_owner("owned", "u1")
    assert db.session_owner("owned") == "u1"
    ensure_session_access("owned", {"id": "u1"})              # owner: ok
    with pytest.raises(HTTPException):
        ensure_session_access("owned", {"id": "u2"})          # other user: blocked
    with pytest.raises(HTTPException):
        ensure_session_access("owned", None)                  # anonymous: blocked

    # ownership survives subsequent state writes (status updates)
    db.save_state(SessionState(session_id="owned", filename="b.csv",
                               status=SessionStatus.DONE, progress=1.0))
    assert db.session_owner("owned") == "u1"
