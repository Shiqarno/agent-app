import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import user_operations
from app.activation import regenerate_activation
from app.db import get_db
from app.errors import UserAlreadyActivatedError, UserNotFoundError
from app.identity import get_current_user, require_adult
from app.models import TelegramIdentity, User, UserActivation, UserCredential, utcnow
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
    # ids, rather than a per-user existence check, avoids N+1. Telegram
    # connection (Issue #33) is a separate, independent axis, derived the
    # same way from TelegramIdentity existence.
    activated_ids = set(db.scalars(select(UserCredential.user_id)))
    telegram_connected_ids = set(db.scalars(select(TelegramIdentity.user_id)))

    return [
        UserListItemResponse(
            id=u.id,
            name=u.name,
            role=u.role,
            avatar_id=u.avatar_id,
            activation_status=(
                ActivationStatus.ACTIVE if u.id in activated_ids else ActivationStatus.PENDING
            ),
            telegram_connected=u.id in telegram_connected_ids,
        )
        for u in users
    ]


@router.post("", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> UserCreateResponse:
    """User + activation creation lives in app.user_operations (Issue #29)
    -- shared with Telegram's create_child, which needs the exact same
    atomic behavior. This endpoint's request/response shape is unchanged.
    """
    new_user, raw_activation_token = user_operations.create_user_with_activation(
        db, name=payload.name, role=payload.role
    )
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
    """The same UserActivation token is the shared onboarding mechanism for
    two independent channels: Web credential setup (routers.auth.activate)
    and Telegram linking (telegram_identity.activate_telegram_identity,
    Issue #23) -- a fresh token here is valid for either, whichever the
    Adult hands to the User first.

    Regeneration is refused only once BOTH channels are already used up
    (Issue #33): a User with Web credentials but no TelegramIdentity still
    has a legitimate reason to get a fresh token (to connect Telegram), and
    vice versa. Before Telegram existed, "has credentials" alone correctly
    meant "nothing left to activate"; that's no longer sufficient now that
    there's a second, independent channel.
    """
    target = db.get(User, user_id)
    if target is None:
        raise UserNotFoundError()

    existing_credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user_id))
    existing_telegram_identity = db.scalar(
        select(TelegramIdentity).where(TelegramIdentity.user_id == user_id)
    )
    if existing_credential is not None and existing_telegram_identity is not None:
        raise UserAlreadyActivatedError()

    activation = db.scalar(select(UserActivation).where(UserActivation.user_id == user_id))
    # Every User created via POST /api/users gets a UserActivation row
    # atomically (Issue #10). The only User that doesn't is the first Adult
    # from /auth/setup, created with credentials directly and no row at
    # all -- previously always caught by the credential check above before
    # reaching here, but that check alone no longer guarantees it now that
    # it's credential-AND-Telegram (Issue #33): that bootstrap Adult has no
    # UserActivation row to regenerate, Telegram or not, so this is treated
    # the same as already fully activated rather than a server error.
    if activation is None:
        raise UserAlreadyActivatedError()

    raw_token = regenerate_activation(activation)
    db.commit()
    db.refresh(activation)
    return ActivationRegenerateResponse(
        activation_token=raw_token,
        expires_at=activation.expires_at,
    )
