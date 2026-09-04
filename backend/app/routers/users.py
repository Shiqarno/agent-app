import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activation import create_activation, regenerate_activation
from app.db import get_db
from app.errors import UserAlreadyActivatedError, UserNotFoundError
from app.identity import get_current_user, require_adult
from app.models import User, UserActivation, UserCredential, utcnow
from app.schemas import (
    ActivationRegenerateResponse,
    ActivationStatus,
    UserAvatarUpdate,
    UserCreate,
    UserCreateResponse,
    UserListItemResponse,
    UserResponse,
)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserListItemResponse])
def list_users(
    user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> list[UserListItemResponse]:
    stmt = select(User).order_by(User.name.asc(), User.id.asc())
    users = list(db.scalars(stmt))

    # Activation status is derived from UserCredential existence (no second
    # persisted source of truth) -- one extra query for all activated user
    # ids, rather than a per-user existence check, avoids N+1.
    activated_ids = set(db.scalars(select(UserCredential.user_id)))

    return [
        UserListItemResponse(
            id=u.id,
            name=u.name,
            role=u.role,
            avatar_id=u.avatar_id,
            activation_status=(
                ActivationStatus.ACTIVE if u.id in activated_ids else ActivationStatus.PENDING
            ),
        )
        for u in users
    ]


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> UserCreateResponse:
    new_user_id = uuid.uuid4()
    new_user = User(id=new_user_id, name=payload.name, role=payload.role)
    db.add(new_user)
    db.flush()
    raw_activation_token = create_activation(db, new_user_id)
    db.commit()
    db.refresh(new_user)
    return UserCreateResponse(
        id=new_user.id,
        name=new_user.name,
        role=new_user.role,
        avatar_id=new_user.avatar_id,
        created_at=new_user.created_at,
        updated_at=new_user.updated_at,
        activation_token=raw_activation_token,
    )


@router.patch("/me", response_model=UserResponse)
def update_my_avatar(
    payload: UserAvatarUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Self-only avatar change (Issue #20): the target is always the
    authenticated user, never a request-supplied id, and no other User
    field is touched. Both Adult and Child may call this -- unlike every
    other endpoint in this router, it is not Adult-only.
    """
    user.avatar_id = payload.avatar_id
    user.updated_at = utcnow()
    db.commit()
    db.refresh(user)
    # See app.routers.auth.me() for why this is a plain lookup with a safe
    # default rather than an invariant assert.
    credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
    return UserResponse(
        id=user.id,
        name=user.name,
        role=user.role,
        avatar_id=user.avatar_id,
        pin_configured=credential is not None and credential.pin_hash is not None,
    )


@router.post("/{user_id}/activation", response_model=ActivationRegenerateResponse)
def regenerate_user_activation(
    user_id: uuid.UUID, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> ActivationRegenerateResponse:
    target = db.get(User, user_id)
    if target is None:
        raise UserNotFoundError()

    existing_credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user_id))
    if existing_credential is not None:
        raise UserAlreadyActivatedError()

    activation = db.scalar(select(UserActivation).where(UserActivation.user_id == user_id))
    # Every User created via POST /api/users gets a UserActivation row
    # atomically (Issue #10). The only User that doesn't is the first Adult
    # from /auth/setup, which is created with credentials directly -- and
    # that case is already caught by the check above, so a pending user here
    # is always guaranteed to have one.
    assert activation is not None, "pending User is missing its UserActivation row"

    raw_token = regenerate_activation(activation)
    db.commit()
    db.refresh(activation)
    return ActivationRegenerateResponse(
        activation_token=raw_token,
        expires_at=activation.expires_at,
    )
