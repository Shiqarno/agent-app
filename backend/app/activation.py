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
