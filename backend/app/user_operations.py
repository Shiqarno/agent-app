import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activation import create_activation, regenerate_activation
from app.models import TelegramIdentity, User, UserActivation, UserRole
from app.schemas import UserCreate


class UserOperationError(Exception):
    """Base for every User-management Application-layer failure (Issue #29).
    Framework-agnostic on purpose -- this module knows nothing about
    FastAPI or the Telegram bot library; each adapter that calls it is
    responsible for translating these into its own presentation.
    """


class NotAnAdultError(UserOperationError):
    """Only an Adult may perform this User-management operation."""


class UserNotFoundError(UserOperationError):
    """No eligible User exists with this id for the requested operation --
    covers both "doesn't exist" and "exists but isn't a Child", collapsed
    into one error so a crafted callback can't distinguish the two.
    """


class UserAlreadyConnectedError(UserOperationError):
    """The target User already has a TelegramIdentity. Generating a fresh
    activation link is onboarding for not-yet-connected Users only
    (Issue #29 section 7/8) -- never a reconnect mechanism, which stays
    out of scope and untouched.
    """


class InvalidNameError(UserOperationError):
    """The provided name failed validation. Carries a human-readable
    message (reusing the existing UserCreate Pydantic validation) so the
    Telegram adapter can show exactly why, without re-deriving the rule.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def create_user_with_activation(db: Session, *, name: str, role: UserRole) -> tuple[User, str]:
    """Atomically creates a User and its initial UserActivation, returning
    the raw (unhashed, one-time-visible) activation token. Shared by the
    Web `POST /api/users` endpoint and Telegram's create_child -- the only
    two places that ever create a User this way, with identical semantics
    between them. The caller is responsible for its own authorization
    check before calling this.
    """
    new_user = User(name=name, role=role)
    db.add(new_user)
    db.flush()
    raw_token = create_activation(db, new_user.id)
    db.commit()
    db.refresh(new_user)
    return new_user, raw_token


def get_users(db: Session, actor: User) -> list[tuple[User, bool]]:
    """Every User, paired with whether they currently have a connected
    TelegramIdentity (Issue #29 section 2/5). Deliberately independent of
    Web's `UserListItemResponse.activation_status`, which reflects
    UserCredential (Web login) existence -- a separate axis from Telegram
    connection.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    users = list(db.scalars(select(User).order_by(User.name.asc(), User.id.asc())))
    connected_ids = set(db.scalars(select(TelegramIdentity.user_id)))
    return [(user, user.id in connected_ids) for user in users]


def create_child(db: Session, actor: User, *, name: str) -> tuple[User, str]:
    """Creates a new Child and its initial activation (Issue #29 section 3).
    Direct assignment/ownership is not part of this operation -- there is
    no Adult<->Child relationship recorded anywhere.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    try:
        payload = UserCreate(name=name, role=UserRole.CHILD)
    except ValidationError as exc:
        message: str = exc.errors()[0]["msg"]
        raise InvalidNameError(message.removeprefix("Value error, ")) from exc

    return create_user_with_activation(db, name=payload.name, role=UserRole.CHILD)


def generate_activation_token(db: Session, actor: User, target_user_id: uuid.UUID) -> str:
    """A fresh activation token for a Child not currently connected to
    Telegram (Issue #29 section 6), reusing the existing regeneration
    mechanism (one valid token at a time, 72h TTL, single-use, previous
    token invalidated on commit). Refuses outright if the target already
    has a TelegramIdentity -- this is onboarding, never a reconnect path
    (section 7/8), regardless of Web credential state.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    target = db.get(User, target_user_id)
    if target is None or target.role != UserRole.CHILD:
        raise UserNotFoundError()

    existing_identity = db.scalar(
        select(TelegramIdentity).where(TelegramIdentity.user_id == target_user_id)
    )
    if existing_identity is not None:
        raise UserAlreadyConnectedError()

    activation = db.scalar(select(UserActivation).where(UserActivation.user_id == target_user_id))
    assert activation is not None, (
        "a Child created via create_child always has a UserActivation row"
    )

    raw_token = regenerate_activation(activation)
    db.commit()
    return raw_token
