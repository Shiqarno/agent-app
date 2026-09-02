import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activation import create_activation
from app.db import get_db
from app.identity import require_adult
from app.models import User
from app.schemas import UserCreate, UserCreateResponse, UserResponse

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(user: User = Depends(require_adult), db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.name.asc(), User.id.asc())
    return list(db.scalars(stmt))


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> User:
    new_user_id = uuid.uuid4()
    new_user = User(id=new_user_id, name=payload.name, role=payload.role)
    db.add(new_user)
    db.flush()
    create_activation(db, new_user_id)
    db.commit()
    db.refresh(new_user)
    return new_user
