"""Persistence layer: sessions and reports (SQLite by default, Postgres in prod)."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from api.config import get_settings
from api.models.report import Report
from api.models.session import SessionState

logger = logging.getLogger(__name__)
Base = declarative_base()


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    filename = Column(String(512), nullable=False)
    status = Column(String(32), nullable=False, default="uploaded")
    progress = Column(Float, nullable=False, default=0.0)
    language = Column(String(8), nullable=False, default="en")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    state_json = Column(Text, nullable=False)
    # null = anonymous/legacy session (publicly accessible); otherwise the owning user
    owner_id = Column(String(36), nullable=True, index=True)


class EventRecord(Base):
    """Append-only progress events consumed by the SSE stream."""

    __tablename__ = "events"

    id = Column(String(64), primary_key=True)
    session_id = Column(String(36), nullable=False, index=True)
    seq = Column(Float, nullable=False)  # monotonic ordering key (time-based)
    type = Column(String(48), nullable=False)
    payload = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ReportRecord(Base):
    __tablename__ = "reports"

    session_id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    report_json = Column(Text, nullable=False)
    html = Column(Text, nullable=True)


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuthTokenRecord(Base):
    """Opaque, server-side session tokens (revocable; checked on every request)."""

    __tablename__ = "auth_tokens"

    token = Column(String(64), primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


_engine = None
_SessionLocal = None


def init_db() -> None:
    global _engine, _SessionLocal
    settings = get_settings()
    _engine = create_engine(settings.database_url, future=True,
                            connect_args={"check_same_thread": False}
                            if settings.database_url.startswith("sqlite") else {})
    _SessionLocal = sessionmaker(bind=_engine, future=True)
    Base.metadata.create_all(_engine)
    _migrate_add_owner_id()
    logger.info("database initialised at %s", settings.database_url)


def _migrate_add_owner_id() -> None:
    """Add sessions.owner_id to pre-existing databases (create_all won't alter)."""
    from sqlalchemy import inspect, text

    try:
        cols = [c["name"] for c in inspect(_engine).get_columns("sessions")]
        if "owner_id" not in cols:
            with _engine.begin() as conn:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN owner_id VARCHAR(36)"))
            logger.info("migrated: added sessions.owner_id")
    except Exception:  # noqa: BLE001 — non-fatal; fresh DBs already have the column
        logger.exception("owner_id migration skipped")


def db_session():
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


# -- typed helpers ------------------------------------------------------------

def save_state(state: SessionState) -> None:
    with db_session() as db:
        rec = db.get(SessionRecord, state.session_id)
        payload = state.model_dump_json()
        if rec is None:
            rec = SessionRecord(id=state.session_id, filename=state.filename)
            db.add(rec)
        rec.filename = state.filename
        rec.status = state.status.value
        rec.progress = state.progress
        rec.language = state.language
        rec.state_json = payload
        db.commit()


def load_state(session_id: str) -> SessionState | None:
    with db_session() as db:
        rec = db.get(SessionRecord, session_id)
        if rec is None:
            return None
        return SessionState.model_validate(json.loads(rec.state_json))


def append_event(session_id: str, event_type: str, payload: dict | None = None) -> None:
    import time
    import uuid

    with db_session() as db:
        db.add(EventRecord(
            id=uuid.uuid4().hex, session_id=session_id, seq=time.time(),
            type=event_type, payload=json.dumps(payload or {}, ensure_ascii=False, default=str),
        ))
        db.commit()


def events_since(session_id: str, after_seq: float = 0.0) -> list[dict]:
    from sqlalchemy import select

    with db_session() as db:
        rows = db.execute(
            select(EventRecord)
            .where(EventRecord.session_id == session_id, EventRecord.seq > after_seq)
            .order_by(EventRecord.seq)
        ).scalars().all()
        return [{"seq": r.seq, "type": r.type, **json.loads(r.payload)} for r in rows]


def save_report(report: Report, html: str | None = None) -> None:
    with db_session() as db:
        rec = db.get(ReportRecord, report.session_id)
        if rec is None:
            rec = ReportRecord(session_id=report.session_id)
            db.add(rec)
        rec.report_json = report.model_dump_json()
        rec.html = html
        db.commit()


def load_report(session_id: str) -> Report | None:
    with db_session() as db:
        rec = db.get(ReportRecord, session_id)
        if rec is None:
            return None
        return Report.model_validate(json.loads(rec.report_json))


# -- session ownership --------------------------------------------------------

def set_session_owner(session_id: str, owner_id: str) -> None:
    with db_session() as db:
        rec = db.get(SessionRecord, session_id)
        if rec is not None:
            rec.owner_id = owner_id
            db.commit()


def session_owner(session_id: str) -> str | None:
    with db_session() as db:
        rec = db.get(SessionRecord, session_id)
        return rec.owner_id if rec is not None else None


# -- auth: users + tokens -----------------------------------------------------

def create_user(user_id: str, email: str, password_hash: str) -> bool:
    """Insert a user; returns False if the email is already taken."""
    from sqlalchemy.exc import IntegrityError

    with db_session() as db:
        db.add(UserRecord(id=user_id, email=email, password_hash=password_hash))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False


def get_user_by_email(email: str) -> dict | None:
    """Internal lookup — includes the password hash for login verification."""
    from sqlalchemy import select

    with db_session() as db:
        rec = db.execute(select(UserRecord).where(UserRecord.email == email)).scalar_one_or_none()
        if rec is None:
            return None
        return {"id": rec.id, "email": rec.email, "password_hash": rec.password_hash}


def get_user(user_id: str) -> dict | None:
    """Public user view (no password hash)."""
    with db_session() as db:
        rec = db.get(UserRecord, user_id)
        return None if rec is None else {"id": rec.id, "email": rec.email}


def store_token(token: str, user_id: str, expires_at: datetime) -> None:
    with db_session() as db:
        db.add(AuthTokenRecord(token=token, user_id=user_id, expires_at=expires_at))
        db.commit()


def user_id_for_token(token: str) -> str | None:
    """Resolve a token to its user, honouring expiry (expired tokens are purged)."""
    with db_session() as db:
        rec = db.get(AuthTokenRecord, token)
        if rec is None:
            return None
        if rec.expires_at < datetime.utcnow():
            db.delete(rec)
            db.commit()
            return None
        return rec.user_id


def delete_token(token: str) -> None:
    with db_session() as db:
        rec = db.get(AuthTokenRecord, token)
        if rec is not None:
            db.delete(rec)
            db.commit()


# session statuses that mean "a pipeline was actively running"
RUNNING_STATUSES = ("planning", "cleaning", "analyzing", "interpreting", "verifying")


def recover_orphaned_jobs() -> int:
    """Fail sessions left mid-run (e.g. by a server restart).

    Analyses run in-process; a restart loses them and the session would otherwise
    stay 'analyzing' forever. Marking them failed lets the UI offer a retry.
    Returns the number of sessions recovered.
    """
    from sqlalchemy import select

    with db_session() as db:
        rows = db.execute(
            select(SessionRecord).where(SessionRecord.status.in_(RUNNING_STATUSES))
        ).scalars().all()
        for rec in rows:
            rec.status = "failed"
            try:
                state = json.loads(rec.state_json)
                state["status"] = "failed"
                state["error"] = ("Analysis was interrupted by a server restart. "
                                  "Please run it again.")
                rec.state_json = json.dumps(state)
            except (ValueError, TypeError):  # malformed state — status flip still applies
                pass
        if rows:
            db.commit()
        return len(rows)
