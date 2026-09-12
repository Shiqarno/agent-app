import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activation import InvalidActivationError, resolve_activation
from app.models import TelegramIdentity, User, utcnow


class TelegramActivationError(Exception):
    """Base for every Telegram-activation failure (Issue #23). Framework-
    agnostic on purpose -- this module knows nothing about FastAPI or the
    Telegram bot library; the adapter that calls it (currently only the
    Telegram bot, but any future one could) is responsible for translating
    these into its own presentation.
    """


class TelegramActivationInvalidError(TelegramActivationError):
    """The activation token is missing, expired, or already used."""


class TelegramAccountAlreadyLinkedError(TelegramActivationError):
    """The current Telegram account is already connected to a *different*
    User. Never silently reassign it -- the caller must obtain a fresh
    activation for the correct User instead.
    """


def resolve_user_by_telegram_id(db: Session, telegram_user_id: int) -> User | None:
    """telegram_user_id -> User, or None if this Telegram account isn't
    connected to anyone yet. This is the one place a raw Telegram id is
    translated into a User -- callers pass the resulting User into ordinary
    business operations from here on, never the Telegram id itself.
    """
    identity = db.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == telegram_user_id)
    )
    if identity is None:
        return None
    return db.get(User, identity.user_id)


def get_telegram_user_id(db: Session, user_id: uuid.UUID) -> int | None:
    """user_id -> telegram_user_id, or None if this User has no Telegram
    account connected -- the inverse of resolve_user_by_telegram_id, used
    by outbound notification delivery (Issue: Telegram notifications),
    never by callback/command handling, which always resolves the other
    direction.
    """
    return db.scalar(
        select(TelegramIdentity.telegram_user_id).where(TelegramIdentity.user_id == user_id)
    )


def activate_telegram_identity(db: Session, raw_token: str, telegram_user_id: int) -> User:
    """Connects `telegram_user_id` to the User the activation token belongs
    to (Issue #23). The Application-layer boundary for Telegram identity:
    no FastAPI, no Telegram `Update`, no presentation text -- callers
    translate the exceptions below into whatever their own interface needs.

    Cases (per Issue #23 spec):
      A. User has no TelegramIdentity yet -> create one.
      B. User already has *this* Telegram account -> no-op, still consumes
         the activation (idempotent success).
      C. User already has a *different* Telegram account -> reconnect: the
         same row's `telegram_user_id` is updated in place, so the old
         value stays valid right up until this transaction actually
         commits, never before.
      D. This Telegram account already belongs to a *different* User ->
         refuse; nothing is changed.
      E. Activation is invalid/expired/used -> refuse; nothing is changed.

    Concurrency: deliberately no `SELECT ... FOR UPDATE` here. Unlike the
    PIN-lockout counter or a Task's is_active slot (which need a fresh read
    to make a conditional decision), this operation is a pure "establish a
    uniqueness-constrained fact" -- exactly the shape of the existing
    UserCredential.email pattern (Issue #9). The single commit below is
    guarded by the same `IntegrityError` catch: if two concurrent attempts
    race past the pre-checks, the database's UNIQUE constraints on
    `user_id`/`telegram_user_id` are the actual integrity boundary, and
    whichever transaction loses gets a clean `TelegramAccountAlreadyLinkedError`
    instead of a lost update or a duplicate row.
    """
    try:
        activation, intended_user = resolve_activation(db, raw_token)
    except InvalidActivationError as exc:
        raise TelegramActivationInvalidError() from exc

    # Case D pre-check: a clear error in the common (non-racing) case. The
    # UNIQUE constraint on telegram_user_id is what actually guarantees
    # this under concurrency -- see the IntegrityError handling below.
    other_identity = db.scalar(
        select(TelegramIdentity).where(TelegramIdentity.telegram_user_id == telegram_user_id)
    )
    if other_identity is not None and other_identity.user_id != intended_user.id:
        raise TelegramAccountAlreadyLinkedError()

    existing_identity = db.scalar(
        select(TelegramIdentity).where(TelegramIdentity.user_id == intended_user.id)
    )
    if existing_identity is None:
        db.add(TelegramIdentity(user_id=intended_user.id, telegram_user_id=telegram_user_id))
    elif existing_identity.telegram_user_id != telegram_user_id:
        existing_identity.telegram_user_id = telegram_user_id
    # else: already exactly this account (Case B) -- nothing to change.

    activation.used_at = utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TelegramAccountAlreadyLinkedError() from exc

    db.refresh(intended_user)
    return intended_user
