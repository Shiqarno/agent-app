import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import UserActivation, utcnow
from app.security import generate_session_token, hash_token

ACTIVATION_TOKEN_TTL = timedelta(hours=72)


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
