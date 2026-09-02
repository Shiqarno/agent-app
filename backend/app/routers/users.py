from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.identity import require_adult
from app.models import User
from app.schemas import UserResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(user: User = Depends(require_adult), db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.name.asc(), User.id.asc())
    return list(db.scalars(stmt))
