import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.csrf import CSRF_COOKIE_NAME
from app.db import get_db
from app.errors import (
    EmailAlreadyInUseError,
    InvalidActivationTokenError,
    InvalidCredentialsError,
    InvalidSetupTokenError,
    PinLockedError,
    SetupAlreadyCompletedError,
    UserAlreadyActivatedError,
)
from app.identity import SESSION_COOKIE_NAME, get_current_user
from app.models import User, UserActivation, UserCredential, UserRole, UserSession, utcnow
from app.schemas import (
    ActivateRequest,
    LoginRequest,
    PinLoginRequest,
    PinSetupRequest,
    ProfileResponse,
    SetupRequest,
    UserResponse,
)
from app.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_pin,
    hash_token,
    normalize_email,
    verify_password,
    verify_pin,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL = timedelta(days=7)

# Simple, fixed-threshold lockout (Issue #22): a 4-digit PIN has only 10,000
# combinations, so unlimited online guessing must be prevented, but the
# lockout must also not be permanent. No escalating backoff -- a flat
# threshold and duration is easy to reason about and to test.
PIN_MAX_FAILED_ATTEMPTS = 5
PIN_LOCKOUT_DURATION = timedelta(minutes=5)


def _user_response(user: User, credential: UserCredential) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        role=user.role,
        avatar_id=user.avatar_id,
        pin_configured=credential.pin_hash is not None,
    )


def _get_credential_for_update(db: Session, user_id: uuid.UUID) -> UserCredential | None:
    """Loads a UserCredential with its row lock held for the rest of the
    transaction. PIN verification reads `pin_locked_until`/`pin_hash`, then
    conditionally writes `pin_failed_attempts`/`pin_locked_until` -- without
    a lock, two concurrent PIN attempts could both read the same
    pre-attempt failure count and each write back count+1, losing one
    increment (and, worse, one of two concurrent *correct*-then-wrong races
    could clear a lockout the other was about to set). FOR UPDATE serializes
    them, matching this project's established pattern (see
    `_get_task_for_update`, `_get_execution_for_update`).
    """
    stmt = select(UserCredential).where(UserCredential.user_id == user_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


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
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserResponse:
    email = normalize_email(payload.email)
    credential = db.scalar(select(UserCredential).where(UserCredential.email == email))
    # `password_hash is None` means "no password configured" (Issue #22) --
    # treated as a normal non-match, not a distinct error.
    if (
        credential is None
        or credential.password_hash is None
        or not verify_password(payload.password, credential.password_hash)
    ):
        raise InvalidCredentialsError()

    user = db.get(User, credential.user_id)
    if user is None:
        raise InvalidCredentialsError()

    raw_token, csrf_token = _issue_session(db, user.id)
    db.commit()
    db.refresh(user)
    _set_session_cookies(response, raw_token, csrf_token)
    return _user_response(user, credential)


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
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    # A real session can only ever be issued alongside a UserCredential (see
    # login/pin_login/setup/activate, all of which create both atomically),
    # so this is always found in production. Tests that mint a session
    # directly (bypassing those flows, e.g. via conftest.auth()) commonly
    # skip creating a credential too, since most of them have nothing to do
    # with credentials -- so this stays a plain lookup with a safe default
    # rather than an invariant assert.
    credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
    return UserResponse(
        id=user.id,
        name=user.name,
        role=user.role,
        avatar_id=user.avatar_id,
        pin_configured=credential is not None and credential.pin_hash is not None,
    )


@router.get("/profiles", response_model=list[ProfileResponse])
def list_profiles(db: Session = Depends(get_db)) -> list[User]:
    """Unauthenticated by design -- this is what the default profile-picker
    login screen renders before any session exists (Issue #22). Only users
    who can actually complete PIN login are listed: a pending (unactivated)
    user has no credential at all, and an existing pre-PIN user has a
    credential but `pin_hash IS NULL` until they complete mandatory PIN
    setup via the password-login fallback -- either way, showing their card
    here would lead to a PIN screen that can never succeed. Once that
    existing user finishes PIN setup, they start appearing here too.
    """
    stmt = (
        select(User)
        .join(UserCredential, UserCredential.user_id == User.id)
        .where(UserCredential.pin_hash.is_not(None))
        .order_by(User.name.asc(), User.id.asc())
    )
    return list(db.scalars(stmt))


@router.post("/pin-login", response_model=UserResponse)
def pin_login(
    payload: PinLoginRequest, response: Response, db: Session = Depends(get_db)
) -> UserResponse:
    credential = _get_credential_for_update(db, payload.user_id)
    if credential is None or credential.pin_hash is None:
        # No such user, or an existing user who hasn't set up a PIN yet --
        # both look identical to the caller (Issue #22: never reveal which).
        raise InvalidCredentialsError()

    if credential.pin_locked_until is not None and credential.pin_locked_until > utcnow():
        # Locked out: don't even attempt verification, and don't consume or
        # reset the counter -- a request while locked changes nothing.
        raise PinLockedError()

    if not verify_pin(payload.pin, credential.pin_hash):
        credential.pin_failed_attempts += 1
        if credential.pin_failed_attempts >= PIN_MAX_FAILED_ATTEMPTS:
            credential.pin_locked_until = utcnow() + PIN_LOCKOUT_DURATION
        db.commit()
        raise InvalidCredentialsError()

    credential.pin_failed_attempts = 0
    credential.pin_locked_until = None

    user = db.get(User, credential.user_id)
    if user is None:
        raise InvalidCredentialsError()

    raw_token, csrf_token = _issue_session(db, user.id)
    db.commit()
    db.refresh(user)
    _set_session_cookies(response, raw_token, csrf_token)
    return _user_response(user, credential)


@router.patch("/pin", response_model=UserResponse)
def setup_pin(
    payload: PinSetupRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Self-only PIN (re)configuration -- the target is always the
    authenticated user, never a request-supplied id (Issue #22). Used both
    for an existing password-only user's mandatory first-time PIN setup and
    for changing an already-configured PIN.
    """
    credential = _get_credential_for_update(db, user.id)
    assert credential is not None, "authenticated user is missing a UserCredential row"

    credential.pin_hash = hash_pin(payload.pin)
    credential.pin_failed_attempts = 0
    credential.pin_locked_until = None
    credential.updated_at = utcnow()
    db.commit()
    db.refresh(user)
    return _user_response(user, credential)


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def setup(
    payload: SetupRequest,
    response: Response,
    db: Session = Depends(get_db),
    x_setup_token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> UserResponse:
    if not settings.initial_setup_token or x_setup_token != settings.initial_setup_token:
        raise InvalidSetupTokenError()

    user_count = db.scalar(select(func.count()).select_from(User))
    if user_count:
        raise SetupAlreadyCompletedError()

    user_id = uuid.uuid4()
    user = User(id=user_id, name=payload.name, role=UserRole.ADULT)
    db.add(user)
    db.flush()

    credential = UserCredential(
        user_id=user_id,
        email=normalize_email(payload.email),
        pin_hash=hash_pin(payload.pin),
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(credential)
    raw_token, csrf_token = _issue_session(db, user_id)
    db.commit()
    db.refresh(user)
    _set_session_cookies(response, raw_token, csrf_token)
    return _user_response(user, credential)


@router.post("/activate", response_model=UserResponse)
def activate(
    payload: ActivateRequest, response: Response, db: Session = Depends(get_db)
) -> UserResponse:
    activation = db.scalar(
        select(UserActivation).where(UserActivation.token_hash == hash_token(payload.token))
    )
    if activation is None or activation.used_at is not None or activation.expires_at < utcnow():
        raise InvalidActivationTokenError()

    user = db.get(User, activation.user_id)
    if user is None:
        raise InvalidActivationTokenError()

    existing_credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
    if existing_credential is not None:
        raise UserAlreadyActivatedError()

    email = normalize_email(payload.email)
    email_taken = db.scalar(select(UserCredential).where(UserCredential.email == email))
    if email_taken is not None:
        raise EmailAlreadyInUseError()

    credential = UserCredential(
        user_id=user.id,
        email=email,
        pin_hash=hash_pin(payload.pin),
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(credential)
    activation.used_at = utcnow()

    raw_token, csrf_token = _issue_session(db, user.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        detail = str(exc.orig)
        if "user_credentials_user_id_key" in detail:
            raise UserAlreadyActivatedError() from exc
        if "user_credentials_email_key" in detail:
            raise EmailAlreadyInUseError() from exc
        raise InvalidActivationTokenError() from exc

    db.refresh(user)
    _set_session_cookies(response, raw_token, csrf_token)
    return _user_response(user, credential)
