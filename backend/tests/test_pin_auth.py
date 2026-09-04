import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db import SessionLocal
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import User, UserCredential, UserRole, UserSession, utcnow
from app.routers.auth import PIN_MAX_FAILED_ATTEMPTS
from app.security import hash_password, hash_pin, verify_pin

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD
PASSWORD = "a sufficiently long passphrase 1"


def create_credential(
    db_session: Session,
    user: User,
    *,
    email: str | None = None,
    password: str | None = PASSWORD,
    pin: str | None = None,
) -> UserCredential:
    """Flexible credential builder for PIN-auth scenarios: a `password=None`
    user has no password (PIN-only), a `pin=None` user has no PIN yet (the
    pre-Issue-#22 "existing user" shape), and both may be set at once.
    """
    credential = UserCredential(
        user_id=user.id,
        email=email or f"{uuid.uuid4()}@example.com",
        password_hash=hash_password(password) if password else None,
        pin_hash=hash_pin(pin) if pin else None,
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


def real_session_headers(session: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Like conftest.auth(), but against an explicitly supplied, real,
    independently-committing session -- for true-concurrency tests that
    intentionally bypass the shared savepoint-isolated db_session fixture.
    """
    raw_token = secrets.token_urlsafe(32)
    csrf_value = secrets.token_urlsafe(16)
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=utcnow() + timedelta(days=7),
        )
    )
    session.commit()
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={raw_token}; {CSRF_COOKIE_NAME}={csrf_value}",
        CSRF_HEADER_NAME: csrf_value,
    }


# =========================================================================================
# Profile discovery: GET /api/auth/profiles
# =========================================================================================


def test_profiles_endpoint_requires_no_authentication(client: TestClient) -> None:
    response = client.get("/api/auth/profiles")

    assert response.status_code == 200


def test_profiles_returns_only_activated_users_with_minimal_fields(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT, "Alice")
    create_credential(db_session, adult, pin="1234")
    make_user(CHILD, "Pending Kid")  # no credential at all -- must not appear

    response = client.get("/api/auth/profiles")

    assert response.status_code == 200
    body = response.json()
    ids = {entry["id"] for entry in body}
    assert str(adult.id) in ids
    assert all(entry["id"] != "" for entry in body)
    for entry in body:
        assert set(entry.keys()) == {"id", "name", "avatar_id"}


def test_pending_user_does_not_appear_in_profiles(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    pending = make_user(CHILD, "Never Activated")

    response = client.get("/api/auth/profiles")

    ids = {entry["id"] for entry in response.json()}
    assert str(pending.id) not in ids


def test_existing_user_without_pin_does_not_appear_in_profiles(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    """An existing (pre-Issue-#22) user has a credential but no PIN yet --
    showing them here would lead to a PIN screen that can never succeed;
    they must complete password-login + mandatory PIN setup first.
    """
    existing = make_user(ADULT, "Password Only")
    create_credential(db_session, existing, password=PASSWORD, pin=None)

    response = client.get("/api/auth/profiles")

    ids = {entry["id"] for entry in response.json()}
    assert str(existing.id) not in ids


def test_user_appears_in_profiles_once_they_complete_pin_setup(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    existing = make_user(ADULT, "Password Only")
    create_credential(db_session, existing, password=PASSWORD, pin=None)
    assert str(existing.id) not in {e["id"] for e in client.get("/api/auth/profiles").json()}

    client.patch("/api/auth/pin", json={"pin": "1234"}, headers=auth(existing))

    response = client.get("/api/auth/profiles")
    ids = {entry["id"] for entry in response.json()}
    assert str(existing.id) in ids


def test_profiles_does_not_expose_credential_or_activation_data(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, email="secret@example.com", pin="1234")

    response = client.get("/api/auth/profiles")

    assert "secret@example.com" not in response.text
    assert "password_hash" not in response.text
    assert "pin_hash" not in response.text
    assert "$argon2id$" not in response.text
    assert "activation" not in response.text.lower()


def test_multiple_users_may_share_an_avatar_and_both_appear(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT, "Same Avatar A")
    child = make_user(CHILD, "Same Avatar B")
    create_credential(db_session, adult, pin="1234")
    create_credential(db_session, child, pin="1234")
    adult.avatar_id = child.avatar_id
    db_session.commit()

    response = client.get("/api/auth/profiles")

    ids = {entry["id"] for entry in response.json()}
    assert str(adult.id) in ids
    assert str(child.id) in ids


def test_profiles_are_ordered_by_name_then_id(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    charlie = make_user(ADULT, "Charlie")
    alice = make_user(ADULT, "Alice")
    bob = make_user(CHILD, "Bob")
    for u in (charlie, alice, bob):
        create_credential(db_session, u, pin="1234")

    response = client.get("/api/auth/profiles")

    names = [entry["name"] for entry in response.json()]
    assert names == ["Alice", "Bob", "Charlie"]


# =========================================================================================
# PIN format validation (exercised via PATCH /api/auth/pin)
# =========================================================================================


def test_pin_setup_accepts_all_zeros(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "0000"}, headers=auth(adult))

    assert response.status_code == 200


def test_pin_setup_accepts_a_leading_zero(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "0427"}, headers=auth(adult))

    assert response.status_code == 200


def test_pin_setup_rejects_three_digits(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "123"}, headers=auth(adult))

    assert response.status_code == 422


def test_pin_setup_rejects_five_digits(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "12345"}, headers=auth(adult))

    assert response.status_code == 422


def test_pin_setup_rejects_a_pin_with_a_letter(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "12a4"}, headers=auth(adult))

    assert response.status_code == 422


def test_pin_setup_rejects_all_letters(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "abcd"}, headers=auth(adult))

    assert response.status_code == 422


# =========================================================================================
# PIN login: POST /api/auth/pin-login
# =========================================================================================


def test_valid_pin_authenticates(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "4321"})

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies
    body = response.json()
    assert body["id"] == str(adult.id)
    assert body["pin_configured"] is True


def test_invalid_pin_returns_generic_401(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_successful_pin_login_creates_a_user_session(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")

    client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "4321"})

    sessions = list(db_session.scalars(select(UserSession).where(UserSession.user_id == adult.id)))
    assert len(sessions) == 1


def test_failed_pin_login_creates_no_session(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")

    client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"})

    sessions = list(db_session.scalars(select(UserSession).where(UserSession.user_id == adult.id)))
    assert sessions == []


def test_password_only_user_cannot_pin_login(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, password=PASSWORD, pin=None)

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "1234"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_pin_only_user_with_no_password_can_pin_login(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, password=None, pin="9876")

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "9876"})

    assert response.status_code == 200


def test_nonexistent_user_id_returns_the_same_generic_401(client: TestClient) -> None:
    response = client.post(
        "/api/auth/pin-login", json={"user_id": str(uuid.uuid4()), "pin": "1234"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_pin_login_is_exempt_from_csrf(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    """Mirrors /login's CSRF exemption: establishing a *new* session must not
    be gated by a stale, unrelated session cookie already present.
    """
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")
    other = make_user(ADULT, "Other")
    stale_cookie = auth(other)["Cookie"]

    response = client.post(
        "/api/auth/pin-login",
        json={"user_id": str(adult.id), "pin": "4321"},
        headers={"Cookie": stale_cookie},
    )

    assert response.status_code == 200


# =========================================================================================
# Lockout
# =========================================================================================


def test_repeated_failures_increment_the_counter(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="4321")

    for _ in range(3):
        client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"})

    db_session.refresh(credential)
    assert credential.pin_failed_attempts == 3


def test_reaching_the_threshold_locks_the_account(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="4321")

    last_response = None
    for _ in range(PIN_MAX_FAILED_ATTEMPTS):
        last_response = client.post(
            "/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"}
        )

    db_session.refresh(credential)
    assert credential.pin_locked_until is not None
    assert credential.pin_locked_until > utcnow()
    # The very attempt that crosses the threshold is itself still a wrong-PIN
    # 401 (the lock is set as a *consequence* of that failure, not detected
    # until the *next* attempt) -- confirm that, then confirm the lock bites.
    assert last_response is not None
    assert last_response.status_code == 401

    locked_response = client.post(
        "/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"}
    )
    assert locked_response.status_code == 429
    assert locked_response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


def test_locked_account_rejects_even_the_correct_pin(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, pin="4321")

    for _ in range(PIN_MAX_FAILED_ATTEMPTS):
        client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"})

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "4321"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


def test_lock_expires_after_its_duration_elapses(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="4321")
    credential.pin_failed_attempts = PIN_MAX_FAILED_ATTEMPTS
    credential.pin_locked_until = utcnow() - timedelta(seconds=1)  # already expired
    db_session.commit()

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "4321"})

    assert response.status_code == 200


def test_successful_login_resets_failure_state(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="4321")
    credential.pin_failed_attempts = 3
    db_session.commit()

    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "4321"})

    assert response.status_code == 200
    db_session.refresh(credential)
    assert credential.pin_failed_attempts == 0
    assert credential.pin_locked_until is None


def test_concurrent_pin_failures_do_not_lose_increments() -> None:
    """Fires several simultaneous wrong-PIN attempts (fewer than the lockout
    threshold, so the outcome is deterministic regardless of interleaving)
    against real, independently-committing sessions -- matching the
    established pattern (e.g. test_redemptions.py's concurrent-redemption
    test). Without the row lock in `_get_credential_for_update`, two
    attempts can both read the same pre-increment count and each write back
    count+1, losing one.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Pin User", role=ADULT)
    setup_session.add(adult)
    setup_session.commit()
    setup_session.refresh(adult)

    credential = UserCredential(
        user_id=adult.id, email=f"{uuid.uuid4()}@example.com", pin_hash=hash_pin("4321")
    )
    setup_session.add(credential)
    setup_session.commit()
    setup_session.refresh(credential)

    attempt_count = 3
    try:
        barrier = threading.Barrier(attempt_count)

        def attempt_wrong_pin() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                thread_client.post(
                    "/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "0000"}
                )

        threads = [threading.Thread(target=attempt_wrong_pin) for _ in range(attempt_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        setup_session.expire_all()
        setup_session.refresh(credential)
        assert credential.pin_failed_attempts == attempt_count
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(UserCredential).filter_by(user_id=adult.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


# =========================================================================================
# PIN setup: PATCH /api/auth/pin
# =========================================================================================


def test_authenticated_user_can_set_their_own_pin(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    response = client.patch("/api/auth/pin", json={"pin": "5678"}, headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["pin_configured"] is True
    credential = db_session.scalar(select(UserCredential).where(UserCredential.user_id == adult.id))
    assert credential is not None
    assert credential.pin_hash is not None


def test_pin_setup_has_no_mechanism_to_target_another_user(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)
    other = make_user(ADULT, "Other Adult")
    other_credential = create_credential(db_session, other, pin="1111")

    response = client.patch(
        "/api/auth/pin",
        json={"pin": "5678", "user_id": str(other.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(adult.id)
    db_session.refresh(other_credential)
    assert other_credential.pin_hash is not None
    assert verify_pin("1111", other_credential.pin_hash)


def test_pin_setup_invalid_pin_is_rejected_and_credential_unchanged(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="1234")
    original_hash = credential.pin_hash

    response = client.patch("/api/auth/pin", json={"pin": "12ab"}, headers=auth(adult))

    assert response.status_code == 422
    db_session.refresh(credential)
    assert credential.pin_hash == original_hash


def test_successful_setup_resets_failure_state(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    credential = create_credential(db_session, adult, pin="1234")
    credential.pin_failed_attempts = 4
    credential.pin_locked_until = utcnow() + timedelta(minutes=5)
    db_session.commit()

    client.patch("/api/auth/pin", json={"pin": "5678"}, headers=auth(adult))

    db_session.refresh(credential)
    assert credential.pin_failed_attempts == 0
    assert credential.pin_locked_until is None


def test_pin_login_works_after_setup(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult)

    client.patch("/api/auth/pin", json={"pin": "5678"}, headers=auth(adult))
    response = client.post("/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "5678"})

    assert response.status_code == 200


def test_pin_setup_requires_authentication(client: TestClient) -> None:
    response = client.patch("/api/auth/pin", json={"pin": "1234"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_concurrent_pin_setup_leaves_a_consistent_final_state() -> None:
    """Two different PINs submitted near-simultaneously for the same user
    must leave exactly one of them as the real, working final PIN -- never a
    corrupted/partial state.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Setup User", role=ADULT)
    setup_session.add(adult)
    setup_session.commit()
    setup_session.refresh(adult)

    credential = UserCredential(user_id=adult.id, email=f"{uuid.uuid4()}@example.com")
    setup_session.add(credential)
    setup_session.commit()

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        barrier = threading.Barrier(2)
        candidates = ["1111", "2222"]

        def attempt_setup(pin: str) -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                thread_client.patch("/api/auth/pin", json={"pin": pin}, headers=auth_headers)

        threads = [threading.Thread(target=attempt_setup, args=(pin,)) for pin in candidates]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with TestClient(app) as final_client:
            results = [
                final_client.post(
                    "/api/auth/pin-login", json={"user_id": str(adult.id), "pin": pin}
                ).status_code
                for pin in candidates
            ]
        # Each pin-login attempt above only "counts" the final row state at
        # the time it runs, and a successful one resets failure state -- so
        # rather than asserting an exact [200, 401]/[401, 200] pairing (order-
        # sensitive), assert the real invariant: exactly one candidate is the
        # genuine final PIN.
        assert results.count(200) == 1
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(UserCredential).filter_by(user_id=adult.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


# =========================================================================================
# Existing-user migration behavior
# =========================================================================================


def test_password_only_user_reports_pin_not_configured(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, password=PASSWORD, pin=None)

    response = client.get("/api/auth/me", headers=auth(adult))

    assert response.json()["pin_configured"] is False


def test_password_only_user_can_still_log_in_with_password(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, email="existing@example.com", password=PASSWORD, pin=None)

    response = client.post(
        "/api/auth/login", json={"email": "existing@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200


def test_after_pin_setup_existing_user_reports_configured_and_can_pin_login(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, password=PASSWORD, pin=None)

    client.patch("/api/auth/pin", json={"pin": "1357"}, headers=auth(adult))

    me_response = client.get("/api/auth/me", headers=auth(adult))
    assert me_response.json()["pin_configured"] is True

    pin_login_response = client.post(
        "/api/auth/pin-login", json={"user_id": str(adult.id), "pin": "1357"}
    )
    assert pin_login_response.status_code == 200
