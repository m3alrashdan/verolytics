"""Auth router: register / login / me / logout (built-in email + password).

Exposes ``get_current_user`` (401 if unauthenticated) and ``optional_user``
(None if unauthenticated) as dependencies for protecting other routers.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from api import db
from api.config import get_settings
from api.services.auth import hash_password, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


class Credentials(BaseModel):
    email: str
    password: str


def _issue_token(user_id: str) -> str:
    token = new_token()
    expires = datetime.utcnow() + timedelta(days=get_settings().token_ttl_days)
    db.store_token(token, user_id, expires)
    return token


@router.post("/register")
def register(body: Credentials) -> dict:
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"Password must be at least {MIN_PASSWORD_LEN} characters")
    user_id = uuid.uuid4().hex
    if not db.create_user(user_id, email, hash_password(body.password)):
        raise HTTPException(409, "That email is already registered")
    return {"token": _issue_token(user_id), "user": {"id": user_id, "email": email}}


@router.post("/login")
def login(body: Credentials) -> dict:
    email = body.email.strip().lower()
    user = db.get_user_by_email(email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    return {"token": _issue_token(user["id"]), "user": {"id": user["id"], "email": user["email"]}}


def _token_from_header(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    token = _token_from_header(authorization)
    user_id = db.user_id_for_token(token) if token else None
    user = db.get_user(user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return user


def optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    token = _token_from_header(authorization)
    user_id = db.user_id_for_token(token) if token else None
    return db.get_user(user_id) if user_id else None


def ensure_session_access(session_id: str, user: dict | None) -> None:
    """Guard a session-scoped endpoint: owned sessions are private to their owner.

    Anonymous/legacy sessions (owner None) stay publicly accessible. A 404 (not
    403) is used for owned-but-not-yours so existence isn't leaked.
    """
    owner = db.session_owner(session_id)
    if owner is not None and (user is None or user.get("id") != owner):
        raise HTTPException(404, "Session not found")


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return user


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    token = _token_from_header(authorization)
    if token:
        db.delete_token(token)
    return {"ok": True}
