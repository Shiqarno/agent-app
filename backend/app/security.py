import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# PINs are hashed with the same Argon2 hasher as passwords (Issue #22) --
# Argon2 has no notion of what kind of secret it's hashing, so a second
# implementation would be pure duplication.
def hash_pin(pin: str) -> str:
    return _password_hasher.hash(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    try:
        return _password_hasher.verify(pin_hash, pin)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(16)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
