import contextvars
import hashlib
import secrets
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db import engine, get_db
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import User, UserActivation, UserRole, UserSession, utcnow


@pytest.fixture
def db_session() -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    def _make_user(role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make_user


# --- Session-based test authentication ---------------------------------------------------
#
# Real backend authentication is cookie/session based (Issue #9): there is no
# request header that authenticates a request on its own. Tests still want a
# simple `auth(user)` call usable from any test module without threading a
# session/DB fixture through every call site, so `auth()` below creates a real
# UserSession row (in the current test's own db_session, so it's covered by
# the same per-test savepoint rollback) and returns headers that carry it: a
# `Cookie` header (session + CSRF cookie) plus the matching CSRF header
# required for state-changing requests. This is not a parallel auth
# mechanism -- it drives the exact same session-cookie code path the real
# app uses, just without going through the HTTP login flow for every test.

_active_db_session: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "_active_db_session", default=None
)


@pytest.fixture(autouse=True)
def _bind_active_db_session(db_session: Session) -> Iterator[None]:
    token = _active_db_session.set(db_session)
    try:
        yield
    finally:
        _active_db_session.reset(token)


def auth(user: User) -> dict[str, str]:
    db_session = _active_db_session.get()
    if db_session is None:
        raise RuntimeError("auth() requires a test using the client/db_session fixtures")

    raw_token = secrets.token_urlsafe(32)
    csrf_value = secrets.token_urlsafe(16)
    db_session.add(
        UserSession(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=utcnow() + timedelta(days=7),
        )
    )
    db_session.commit()
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={raw_token}; {CSRF_COOKIE_NAME}={csrf_value}",
        CSRF_HEADER_NAME: csrf_value,
    }


# --- Activation test helper -----------------------------------------------------------
#
# Production never returns a raw activation token (it's hashed before storage,
# same as sessions). Tests get access to it the same way `auth()` bypasses the
# HTTP login flow: by creating the real UserActivation row directly and
# returning the raw token before it's discarded, instead of adding any
# dev-only token-retrieval endpoint.


def create_activation(user: User, *, expires_in: timedelta = timedelta(hours=72)) -> str:
    db_session = _active_db_session.get()
    if db_session is None:
        raise RuntimeError(
            "create_activation() requires a test using the client/db_session fixtures"
        )

    raw_token = secrets.token_urlsafe(32)
    db_session.add(
        UserActivation(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=utcnow() + expires_in,
        )
    )
    db_session.commit()
    return raw_token
