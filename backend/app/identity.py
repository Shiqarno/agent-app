from fastapi import Cookie, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ForbiddenError, UnauthenticatedError
from app.models import User, UserRole, UserSession, utcnow
from app.security import hash_token

SESSION_COOKIE_NAME = "session_token"


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    if session_token is None:
        raise UnauthenticatedError("Missing session")

    token_hash = hash_token(session_token)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    if session is None:
        raise UnauthenticatedError("Invalid session")

    if session.expires_at < utcnow():
        db.delete(session)
        db.commit()
        raise UnauthenticatedError("Session expired")

    user = db.get(User, session.user_id)
    if user is None:
        db.delete(session)
        db.commit()
        raise UnauthenticatedError("Invalid session")

    return user


def require_adult(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADULT:
        raise ForbiddenError("Only adults can perform this action")
    return user
