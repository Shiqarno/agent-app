import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

from conftest import auth, create_activation
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import User, UserActivation, UserCredential, UserRole, UserSession, utcnow
from app.security import hash_password, hash_token, verify_password

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD

PASSWORD = "a sufficiently long passphrase 1"


# --- Activation success --------------------------------------------------------------------


def test_valid_activation_creates_credentials_and_logs_in(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD, "Kid")
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid@example.com", "password": PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(child.id), "name": "Kid", "role": "child"}

    credential = db_session.scalar(select(UserCredential).where(UserCredential.user_id == child.id))
    assert credential is not None
    assert credential.email == "kid@example.com"


def test_activation_marks_the_token_used(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid2@example.com", "password": PASSWORD},
    )

    activation = db_session.scalar(
        select(UserActivation).where(UserActivation.token_hash == hash_token(token))
    )
    assert activation is not None
    assert activation.used_at is not None


def test_activation_creates_an_authenticated_session(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid3@example.com", "password": PASSWORD},
    )

    assert SESSION_COOKIE_NAME in response.cookies
    me_response = client.get(
        "/api/auth/me", cookies={SESSION_COOKIE_NAME: response.cookies[SESSION_COOKIE_NAME]}
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(child.id)


def test_activation_response_never_contains_the_raw_token(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid4@example.com", "password": PASSWORD},
    )

    assert set(response.json().keys()) == {"id", "name", "role"}
    assert token not in response.text


def test_activation_email_is_normalized(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "  Kid5@Example.com  ", "password": PASSWORD},
    )

    assert response.status_code == 200
    credential = db_session.scalar(select(UserCredential).where(UserCredential.user_id == child.id))
    assert credential is not None
    assert credential.email == "kid5@example.com"


def test_activated_user_can_log_in_with_new_credentials(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)
    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid6@example.com", "password": PASSWORD},
    )

    response = client.post(
        "/api/auth/login", json={"email": "kid6@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(child.id)


# --- Invalid / expired / used tokens (generic error, no enumeration) ------------------------


def test_nonexistent_token_returns_generic_400(client: TestClient) -> None:
    response = client.post(
        "/api/auth/activate",
        json={"token": "not-a-real-token", "email": "nobody@example.com", "password": PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_TOKEN"


def test_expired_token_returns_the_same_generic_400(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child, expires_in=timedelta(seconds=-1))

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "expired@example.com", "password": PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_TOKEN"


def test_already_used_token_returns_the_same_generic_400(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)
    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "used@example.com", "password": PASSWORD},
    )

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "used-again@example.com", "password": PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ACTIVATION_TOKEN"


def test_invalid_and_expired_and_used_tokens_share_identical_error_bodies(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child_a = make_user(CHILD, "A")
    child_b = make_user(CHILD, "B")
    expired_token = create_activation(child_a, expires_in=timedelta(seconds=-1))
    used_token = create_activation(child_b)
    client.post(
        "/api/auth/activate",
        json={"token": used_token, "email": "b@example.com", "password": PASSWORD},
    )

    nonexistent = client.post(
        "/api/auth/activate",
        json={"token": "garbage", "email": "x@example.com", "password": PASSWORD},
    )
    expired = client.post(
        "/api/auth/activate",
        json={"token": expired_token, "email": "y@example.com", "password": PASSWORD},
    )
    used = client.post(
        "/api/auth/activate",
        json={"token": used_token, "email": "z@example.com", "password": PASSWORD},
    )

    assert nonexistent.json() == expired.json() == used.json()


# --- Email conflicts ------------------------------------------------------------------------


def test_email_already_in_use_by_another_user_returns_409(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    existing = make_user(ADULT, "Existing")
    db_session.add(
        UserCredential(
            user_id=existing.id,
            email="taken@example.com",
            password_hash=hash_password(PASSWORD),
        )
    )
    db_session.commit()

    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "taken@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_IN_USE"


def test_email_conflict_does_not_modify_the_existing_credential(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    existing = make_user(ADULT, "Existing")
    db_session.add(
        UserCredential(
            user_id=existing.id,
            email="taken2@example.com",
            password_hash=hash_password("original-password-1234"),
        )
    )
    db_session.commit()

    child = make_user(CHILD)
    token = create_activation(child)
    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "taken2@example.com", "password": PASSWORD},
    )

    credential = db_session.scalar(
        select(UserCredential).where(UserCredential.user_id == existing.id)
    )
    assert credential is not None
    assert credential.email == "taken2@example.com"
    assert verify_password("original-password-1234", credential.password_hash)


def test_email_conflict_leaves_the_activation_token_unused(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    existing = make_user(ADULT, "Existing")
    db_session.add(
        UserCredential(
            user_id=existing.id,
            email="taken3@example.com",
            password_hash=hash_password(PASSWORD),
        )
    )
    db_session.commit()

    child = make_user(CHILD)
    token = create_activation(child)
    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "taken3@example.com", "password": PASSWORD},
    )

    activation = db_session.scalar(
        select(UserActivation).where(UserActivation.token_hash == hash_token(token))
    )
    assert activation is not None
    assert activation.used_at is None

    retry = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "not-taken@example.com", "password": PASSWORD},
    )
    assert retry.status_code == 200


# --- Already activated ------------------------------------------------------------------------


def test_reactivating_an_already_activated_user_returns_409(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    db_session.add(
        UserCredential(
            user_id=child.id, email="already@example.com", password_hash=hash_password(PASSWORD)
        )
    )
    db_session.commit()
    token = insert_activation(db_session, child.id)
    db_session.commit()

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "new-email@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_ALREADY_ACTIVATED"


def test_already_activated_conflict_does_not_overwrite_credentials(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    db_session.add(
        UserCredential(
            user_id=child.id,
            email="original@example.com",
            password_hash=hash_password("original-password-1234"),
        )
    )
    db_session.commit()
    token = insert_activation(db_session, child.id)
    db_session.commit()

    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "hijack@example.com", "password": PASSWORD},
    )

    credential = db_session.scalar(select(UserCredential).where(UserCredential.user_id == child.id))
    assert credential is not None
    assert credential.email == "original@example.com"


# --- Password validation --------------------------------------------------------------------


def test_password_shorter_than_minimum_returns_422(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "short@example.com", "password": "too-short"},
    )

    assert response.status_code == 422


def test_missing_email_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post("/api/auth/activate", json={"token": token, "password": PASSWORD})

    assert response.status_code == 422


def test_missing_token_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    response = client.post(
        "/api/auth/activate", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert response.status_code == 422


# --- Security --------------------------------------------------------------------------------


def test_raw_activation_token_is_never_persisted(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    raw_token = insert_activation(db_session, child.id)
    db_session.commit()

    activation = db_session.scalar(select(UserActivation).where(UserActivation.user_id == child.id))
    assert activation is not None
    assert activation.token_hash != raw_token
    assert activation.token_hash == hash_token(raw_token)


def test_password_is_never_returned(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "sec@example.com", "password": PASSWORD},
    )

    assert "password_hash" not in response.text
    assert "$argon2id$" not in response.text


def test_client_supplied_user_id_is_never_trusted(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    other = make_user(CHILD, "Other")
    token = create_activation(child)

    response = client.post(
        "/api/auth/activate",
        json={
            "token": token,
            "email": "trust@example.com",
            "password": PASSWORD,
            "user_id": str(other.id),
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(child.id)


def test_activate_is_exempt_from_csrf_even_with_a_stale_session_cookie(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Mirrors the login/setup CSRF-exemption bug found in Issue #9: a stale,
    unrelated session cookie must not block an otherwise-valid activation.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    token = create_activation(child)
    stale_session_cookie = auth(adult)["Cookie"]

    response = client.post(
        "/api/auth/activate",
        json={"token": token, "email": "csrf@example.com", "password": PASSWORD},
        headers={"Cookie": stale_session_cookie},
    )

    assert response.status_code == 200


# --- Login before activation unaffected -------------------------------------------------------


def test_login_before_activation_returns_the_same_generic_401(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    create_activation(child)  # activation exists, but the user hasn't used it yet

    response = client.post(
        "/api/auth/login", json={"email": "not-yet-activated@example.com", "password": PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "Invalid credentials"


# --- User creation -> activation integration ---------------------------------------------------


def test_creating_a_user_creates_an_activation_record(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    created = client.post(
        "/api/users", json={"name": "New Kid", "role": "child"}, headers=auth(adult)
    ).json()

    activation = db_session.scalar(
        select(UserActivation).where(UserActivation.user_id == uuid.UUID(created["id"]))
    )
    assert activation is not None
    assert activation.used_at is None
    assert activation.expires_at > utcnow()


def test_user_creation_response_includes_the_raw_activation_token(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Issue #11 extends UserCreateResponse: the raw token is now returned
    once, to the creating Adult, so the frontend can present an activation
    link. Every other field is unchanged.
    """
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "New Kid", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 201
    body = response.json()
    expected_keys = {"id", "name", "role", "created_at", "updated_at", "activation_token"}
    assert set(body.keys()) == expected_keys
    assert isinstance(body["activation_token"], str)
    assert body["activation_token"]


def test_returned_activation_token_matches_the_stored_hash(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    created = client.post(
        "/api/users", json={"name": "New Kid", "role": "child"}, headers=auth(adult)
    ).json()

    activation = db_session.scalar(
        select(UserActivation).where(UserActivation.user_id == uuid.UUID(created["id"]))
    )
    assert activation is not None
    assert activation.token_hash != created["activation_token"]
    assert activation.token_hash == hash_token(created["activation_token"])


def test_the_created_users_activation_token_actually_activates_them(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    created = client.post(
        "/api/users", json={"name": "New Kid", "role": "child"}, headers=auth(adult)
    ).json()

    response = client.post(
        "/api/auth/activate",
        json={
            "token": created["activation_token"],
            "email": "newkid@example.com",
            "password": PASSWORD,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_activation_token_is_not_exposed_by_user_discovery(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    client.post("/api/users", json={"name": "New Kid", "role": "child"}, headers=auth(adult))

    response = client.get("/api/users", headers=auth(adult))

    assert response.status_code == 200
    for entry in response.json():
        assert "activation_token" not in entry


# --- Concurrency ------------------------------------------------------------------------------


def test_concurrent_activation_with_the_same_token_succeeds_exactly_once() -> None:
    """Two independently-committing requests race to activate the same
    single-use token. Real Postgres sessions (not the shared savepoint-
    isolated `db_session`/`client` fixtures) are required to reproduce a
    genuine race, matching the pattern used for the redemption concurrency
    test (Issue #6).
    """
    setup_session = SessionLocal()
    child = User(name="Concurrent Kid", role=UserRole.CHILD)
    setup_session.add(child)
    setup_session.commit()
    setup_session.refresh(child)

    raw_token = insert_activation(setup_session, child.id)
    setup_session.commit()

    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def attempt_activate() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    "/api/auth/activate",
                    json={
                        "token": raw_token,
                        "email": "race@example.com",
                        "password": PASSWORD,
                    },
                )
            results.append(response.status_code)

        threads = [threading.Thread(target=attempt_activate) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [200, 409]

        credential_count = setup_session.scalar(
            select(func.count())
            .select_from(UserCredential)
            .where(UserCredential.user_id == child.id)
        )
        assert credential_count == 1

        used_activations = setup_session.scalar(
            select(func.count())
            .select_from(UserActivation)
            .where(UserActivation.user_id == child.id, UserActivation.used_at.is_not(None))
        )
        assert used_activations == 1
    finally:
        setup_session.rollback()
        setup_session.query(UserCredential).filter_by(user_id=child.id).delete()
        setup_session.query(UserSession).filter_by(user_id=child.id).delete()
        setup_session.query(UserActivation).filter_by(user_id=child.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.commit()
        setup_session.close()
