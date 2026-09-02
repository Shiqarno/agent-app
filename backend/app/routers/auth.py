import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.csrf import CSRF_COOKIE_NAME
from app.db import get_db
from app.errors import (
    InvalidCredentialsError,
    InvalidSetupTokenError,
    SetupAlreadyCompletedError,
)
from app.identity import SESSION_COOKIE_NAME, get_current_user
from app.models import User, UserCredential, UserRole, UserSession, utcnow
from app.schemas import LoginRequest, SetupRequest, UserResponse
from app.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    normalize_email,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL = timedelta(days=7)


def _issue_session(db: Session, user_id: uuid.UUID) -> tuple[str, str]:
    """Adds a new UserSession to `db` (uncommitted) and returns (raw_token, csrf_token)."""
    raw_token = generate_session_token()
    csrf_token = generate_csrf_token()
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=utcnow() + SESSION_TTL,
        )
    )
    return raw_token, csrf_token


def _set_session_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    secure = settings.environment == "production"
    max_age = int(SESSION_TTL.total_seconds())
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=max_age,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    email = normalize_email(payload.email)
    credential = db.scalar(select(UserCredential).where(UserCredential.email == email))
    if credential is None or not verify_password(payload.password, credential.password_hash):
        raise InvalidCredentialsError()

    user = db.get(User, credential.user_id)
    if user is None:
        raise InvalidCredentialsError()

    raw_token, csrf_token = _issue_session(db, user.id)
    db.commit()
    _set_session_cookies(response, raw_token, csrf_token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is not None:
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
        )
        if session is not None:
            db.delete(session)
            db.commit()
    _clear_session_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def setup(
    payload: SetupRequest,
    response: Response,
    db: Session = Depends(get_db),
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> User:
    if not settings.initial_setup_token or x_setup_token != settings.initial_setup_token:
        raise InvalidSetupTokenError()

    user_count = db.scalar(select(func.count()).select_from(User))
    if user_count:
        raise SetupAlreadyCompletedError()

    user_id = uuid.uuid4()
    user = User(id=user_id, name=payload.name, role=UserRole.ADULT)
    db.add(user)
    db.flush()

    db.add(
        UserCredential(
            user_id=user_id,
            email=normalize_email(payload.email),
            password_hash=hash_password(payload.password),
        )
    )
    raw_token, csrf_token = _issue_session(db, user_id)
    db.commit()
    db.refresh(user)
    _set_session_cookies(response, raw_token, csrf_token)
    return user
