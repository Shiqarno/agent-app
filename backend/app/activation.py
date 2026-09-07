import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserActivation, utcnow
from app.security import generate_session_token, hash_token

ACTIVATION_TOKEN_TTL = timedelta(hours=72)


class InvalidActivationError(Exception):
    """A raw activation token didn't resolve to a usable UserActivation --
    missing, expired, or already used. Framework-agnostic (no FastAPI, no
    Telegram) so both the Web router and the Telegram identity use case
    (Issue #23) can catch this and translate it into their own error shape.
    """


def create_activation(db: Session, user_id: uuid.UUID) -> str:
    """Adds a new UserActivation to `db` (uncommitted) and returns the raw token."""
    raw_token = generate_session_token()
    db.add(
        UserActivation(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=utcnow() + ACTIVATION_TOKEN_TTL,
        )
    )
    return raw_token


def regenerate_activation(activation: UserActivation) -> str:
    """Replaces `activation`'s token in place (uncommitted) and returns the new
    raw token. Reuses the existing row rather than creating a second one --
    the old token's hash is overwritten, so it stops matching anything as
    soon as this commits.
    """
    raw_token = generate_session_token()
    activation.token_hash = hash_token(raw_token)
    activation.expires_at = utcnow() + ACTIVATION_TOKEN_TTL
    activation.used_at = None
    return raw_token


def resolve_activation(db: Session, raw_token: str) -> tuple[UserActivation, User]:
    """Looks up a UserActivation by its raw token and validates it's usable
    (exists, not expired, not already used), returning it along with the
    User it belongs to. Shared low-level activation mechanics (Issue #23):
    Web activation and Telegram activation both start here, then diverge
    into their own channel-specific behavior.

    Does not lock the row or consume the activation -- callers that intend
    to consume it set `used_at` themselves as part of their own atomic
    unit of work (see routers.auth.activate and
    telegram_identity.activate_telegram_identity), each relying on a
    database-level uniqueness constraint as the final safeguard against two
    concurrent callers both treating the same not-yet-consumed token as
    valid, exactly like this project's existing email-uniqueness pattern.
    """
    activation = db.scalar(
        select(UserActivation).where(UserActivation.token_hash == hash_token(raw_token))
    )
    if activation is None or activation.used_at is not None or activation.expires_at < utcnow():
        raise InvalidActivationError()

    user = db.get(User, activation.user_id)
    if user is None:
        raise InvalidActivationError()

    return activation, user
