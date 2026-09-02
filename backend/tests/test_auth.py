import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.identity import SESSION_COOKIE_NAME
from app.models import User, UserCredential, UserRole, UserSession, utcnow
from app.security import hash_password, hash_token, normalize_email

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD

PASSWORD = "a sufficiently long passphrase 1"


def create_credential(
    db_session: Session, user: User, email: str = "user@example.com", password: str = PASSWORD
) -> UserCredential:
    credential = UserCredential(
        user_id=user.id,
        email=normalize_email(email),
        password_hash=hash_password(password),
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


# --- Login --------------------------------------------------------------------------------


def test_valid_credentials_authenticate_successfully(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT, "Alice")
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(adult.id), "name": "Alice", "role": "adult"}


def test_invalid_password_returns_401(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "totally-wrong-password-1"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_unknown_email_returns_the_same_401(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "whatever-password-here-1"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "Invalid credentials"


def test_email_normalization_works(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "  Alice@Example.com  ")

    response = client.post(
        "/api/auth/login",
        json={"email": "alice@EXAMPLE.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(adult.id)


def test_password_is_never_returned(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )

    assert set(response.json().keys()) == {"id", "name", "role"}


def test_password_hash_is_never_returned(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )

    assert "password_hash" not in response.text
    assert "$argon2id$" not in response.text


def test_session_cookie_is_set(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )

    assert SESSION_COOKIE_NAME in response.cookies
    assert CSRF_COOKIE_NAME in response.cookies
    set_cookie_headers = response.headers.get_list("set-cookie")
    session_cookie_header = next(h for h in set_cookie_headers if h.startswith(SESSION_COOKIE_NAME))
    assert "HttpOnly" in session_cookie_header
    assert "SameSite=lax" in session_cookie_header


def test_raw_session_token_is_not_persisted(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    response = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )
    raw_token = response.cookies[SESSION_COOKIE_NAME]

    session = db_session.scalar(select(UserSession).where(UserSession.user_id == adult.id))
    assert session is not None
    assert session.token_hash != raw_token
    assert session.token_hash == hash_token(raw_token)


def test_multiple_logins_create_independent_sessions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "alice@example.com")

    first = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )
    second = client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD}
    )

    assert first.cookies[SESSION_COOKIE_NAME] != second.cookies[SESSION_COOKIE_NAME]
    all_sessions = list(
        db_session.scalars(select(UserSession).where(UserSession.user_id == adult.id))
    )
    assert len(all_sessions) == 2

    # Both sessions independently authenticate.
    me_first = client.get(
        "/api/auth/me", cookies={SESSION_COOKIE_NAME: first.cookies[SESSION_COOKIE_NAME]}
    )
    me_second = client.get(
        "/api/auth/me", cookies={SESSION_COOKIE_NAME: second.cookies[SESSION_COOKIE_NAME]}
    )
    assert me_first.status_code == 200
    assert me_second.status_code == 200


def test_user_without_credentials_cannot_login(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    make_user(ADULT)  # exists, but no UserCredential row

    response = client.post(
        "/api/auth/login",
        json={"email": "no-credentials@example.com", "password": "whatever-password-here-1"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


# --- Session --------------------------------------------------------------------------------


def test_valid_session_authenticates(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/auth/me", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["id"] == str(adult.id)


def test_missing_session_returns_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_invalid_session_returns_401(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", cookies={SESSION_COOKIE_NAME: "not-a-real-session-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_expired_session_returns_401(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    raw_token = "expired-token-fixture-value"
    db_session.add(
        UserSession(
            user_id=adult.id,
            token_hash=hash_token(raw_token),
            expires_at=utcnow() - timedelta(seconds=1),
        )
    )
    db_session.commit()

    response = client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: raw_token})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_expired_session_is_deleted_opportunistically(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    raw_token = "another-expired-token-fixture"
    db_session.add(
        UserSession(
            user_id=adult.id,
            token_hash=hash_token(raw_token),
            expires_at=utcnow() - timedelta(seconds=1),
        )
    )
    db_session.commit()

    client.get("/api/auth/me", cookies={SESSION_COOKIE_NAME: raw_token})

    remaining = db_session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
    )
    assert remaining is None


# Note (test #15, "session for a deleted/nonexistent User cannot authenticate"):
# not independently testable via a real-database integration test. UserSession
# .user_id carries a NOT NULL foreign key to users.id with no cascading delete
# behavior (Issue #9 explicitly does not introduce User deletion), so it is
# impossible to either (a) insert a UserSession referencing a nonexistent User
# or (b) delete a User while a UserSession still references it -- Postgres
# rejects both at the constraint level. get_current_user() still contains the
# defensive "user is None -> treat as unauthenticated" branch the spec asks
# for (see app/identity.py), covering a future world where deletion exists;
# there is just no way to reach it today without mocking the session query,
# which this suite avoids by convention.


# --- Logout -----------------------------------------------------------------------------


def test_logout_invalidates_current_session(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)

    response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 204
    remaining = db_session.scalar(select(UserSession).where(UserSession.user_id == adult.id))
    assert remaining is None


def test_authenticated_api_becomes_inaccessible_after_logout(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)
    client.post("/api/auth/logout", headers=headers)

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401


def test_logout_without_a_valid_session_is_safe(client: TestClient) -> None:
    response = client.post("/api/auth/logout")

    assert response.status_code == 204


# --- /auth/me -----------------------------------------------------------------------------


def test_me_returns_authenticated_user(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT, "Bob")

    response = client.get("/api/auth/me", headers=auth(adult))

    assert response.status_code == 200
    assert response.json() == {"id": str(adult.id), "name": "Bob", "role": "adult"}


def test_me_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_response_contains_only_public_user_fields(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/auth/me", headers=auth(adult))

    assert set(response.json().keys()) == {"id", "name", "role"}


# --- Setup ------------------------------------------------------------------------------


def test_first_setup_creates_adult_and_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", "setup-secret-1")

    response = client.post(
        "/api/auth/setup",
        json={"name": "Initial Adult", "email": "admin@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "setup-secret-1"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Initial Adult"
    assert body["role"] == "adult"

    user = db_session.get(User, uuid.UUID(body["id"]))
    assert user is not None
    assert user.role == ADULT

    credential = db_session.scalar(
        select(UserCredential).where(UserCredential.user_id == user.id)
    )
    assert credential is not None
    assert credential.email == "admin@example.com"


def test_setup_creates_an_authenticated_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", "setup-secret-2")

    setup_response = client.post(
        "/api/auth/setup",
        json={"name": "Initial Adult", "email": "admin2@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "setup-secret-2"},
    )
    assert SESSION_COOKIE_NAME in setup_response.cookies

    me_response = client.get(
        "/api/auth/me",
        cookies={SESSION_COOKIE_NAME: setup_response.cookies[SESSION_COOKIE_NAME]},
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == setup_response.json()["id"]


def test_setup_cannot_run_when_users_already_exist(
    client: TestClient, make_user: Callable[..., User], monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user(CHILD)  # any existing User, regardless of role, blocks setup
    monkeypatch.setattr(app_settings, "initial_setup_token", "setup-secret-3")

    response = client.post(
        "/api/auth/setup",
        json={"name": "Second Adult", "email": "second@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "setup-secret-3"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SETUP_ALREADY_COMPLETED"


def test_setup_cannot_create_a_second_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", "setup-secret-4")

    first = client.post(
        "/api/auth/setup",
        json={"name": "First Adult", "email": "first@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "setup-secret-4"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/auth/setup",
        json={"name": "Second Adult", "email": "second@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "setup-secret-4"},
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SETUP_ALREADY_COMPLETED"


def test_missing_setup_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", "setup-secret-5")

    response = client.post(
        "/api/auth/setup",
        json={"name": "Adult", "email": "admin@example.com", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SETUP_TOKEN"
    assert db_session.scalar(select(User)) is None


def test_incorrect_setup_token_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", "the-real-secret")

    response = client.post(
        "/api/auth/setup",
        json={"name": "Adult", "email": "admin@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "a-wrong-guess"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SETUP_TOKEN"
    assert db_session.scalar(select(User)) is None


def test_missing_initial_setup_token_configuration_fails_safely(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> None:
    monkeypatch.setattr(app_settings, "initial_setup_token", None)

    response = client.post(
        "/api/auth/setup",
        json={"name": "Adult", "email": "admin@example.com", "password": PASSWORD},
        headers={"X-Setup-Token": "anything-at-all"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SETUP_TOKEN"
    assert db_session.scalar(select(User)) is None


def test_setup_is_transactional(db_session: Session) -> None:
    """Directly exercises the same failure-mid-sequence invariant the /setup
    endpoint depends on (one commit for User + UserCredential + UserSession):
    if any write in that sequence fails, none of it persists. Forcing this
    through the endpoint itself while also satisfying its own "zero users"
    precondition isn't possible (any pre-seeded conflicting data is itself a
    User), so -- matching the project's existing atomicity-test pattern
    (Issues #3 and #6) -- this drives the same session/commit mechanics
    directly.
    """
    existing = User(name="Existing", role=ADULT)
    db_session.add(existing)
    db_session.commit()
    db_session.add(
        UserCredential(
            user_id=existing.id,
            email="taken@example.com",
            password_hash=hash_password(PASSWORD),
        )
    )
    db_session.commit()

    new_user_id = uuid.uuid4()
    db_session.add(User(id=new_user_id, name="New Adult", role=ADULT))
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=new_user_id,
            email="taken@example.com",  # duplicate -> unique constraint violation
            password_hash=hash_password(PASSWORD),
        )
    )
    db_session.add(
        UserSession(
            user_id=new_user_id,
            token_hash=hashlib.sha256(b"irrelevant").hexdigest(),
            expires_at=utcnow() + timedelta(days=7),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(User, new_user_id) is None
    assert (
        db_session.scalar(select(UserSession).where(UserSession.user_id == new_user_id)) is None
    )


# --- X-User-Id no longer authenticates -----------------------------------------------------


def test_x_user_id_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/auth/me", headers={"X-User-Id": str(adult.id)})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_invalid_x_user_id_cannot_override_a_valid_session(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)
    headers["X-User-Id"] = str(uuid.uuid4())  # bogus, unrelated id

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == str(adult.id)


def test_valid_x_user_id_cannot_override_a_missing_session(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/auth/me", headers={"X-User-Id": str(adult.id)})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# --- CSRF -------------------------------------------------------------------------------


def test_valid_csrf_token_allows_state_changing_request(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "Kid", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 201


def test_missing_csrf_header_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)
    del headers[CSRF_HEADER_NAME]

    response = client.post("/api/users", json={"name": "Kid", "role": "child"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_mismatched_csrf_header_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)
    headers[CSRF_HEADER_NAME] = "does-not-match-the-cookie"

    response = client.post("/api/users", json={"name": "Kid", "role": "child"}, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


def test_get_endpoints_do_not_require_csrf_token(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    headers = auth(adult)
    del headers[CSRF_HEADER_NAME]

    response = client.get("/api/users", headers=headers)

    assert response.status_code == 200


# --- Authorization regression -------------------------------------------------------------


def test_authenticated_adult_retains_adult_capabilities(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "Kid", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 201


def test_authenticated_child_retains_child_restrictions(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)

    response = client.post(
        "/api/users", json={"name": "Kid", "role": "child"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
