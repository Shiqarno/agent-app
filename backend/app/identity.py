import uuid

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ForbiddenError, UnauthenticatedError
from app.models import User, UserRole


def get_current_user(
    x_user_id: uuid.UUID | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    if x_user_id is None:
        raise UnauthenticatedError("X-User-Id header is required")
    user = db.get(User, x_user_id)
    if user is None:
        raise UnauthenticatedError("Unknown user")
    return user


def require_adult(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADULT:
        raise ForbiddenError("Only adults can perform this action")
    return user


def require_child(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.CHILD:
        raise ForbiddenError("Only children can perform this action")
    return user
