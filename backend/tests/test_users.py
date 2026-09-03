import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from conftest import auth, create_activation
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db import SessionLocal
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import User, UserActivation, UserCredential, UserRole, UserSession, utcnow
from app.security import hash_password, hash_token

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD
PASSWORD = "a sufficiently long passphrase 1"


def create_credential(
    db_session: Session, user: User, email: str = "user@example.com"
) -> UserCredential:
    credential = UserCredential(user_id=user.id, email=email, password_hash=hash_password(PASSWORD))
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


def real_session_headers(session: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Like conftest.auth(), but against an explicitly supplied, real,
    independently-committing session -- for tests (e.g. the concurrency test
    below) that intentionally bypass the shared savepoint-isolated
    db_session fixture.
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


# --- Adult can discover users -----------------------------------------------------------


def test_adult_can_discover_all_users(client: TestClient, make_user: Callable[..., User]) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")

    response = client.get("/api/users", headers=auth(adult_a))

    assert response.status_code == 200
    body = response.json()
    by_id = {entry["id"]: entry for entry in body}

    assert set(by_id) == {str(adult_a.id), str(adult_b.id), str(child_a.id), str(child_b.id)}
    # make_user() (like the real POST /api/users -> credential-less flow)
    # never gives these a UserCredential, so all are PENDING here.
    assert by_id[str(adult_a.id)] == {
        "id": str(adult_a.id),
        "name": "Adult A",
        "role": "adult",
        "activation_status": "PENDING",
    }
    assert by_id[str(adult_b.id)] == {
        "id": str(adult_b.id),
        "name": "Adult B",
        "role": "adult",
        "activation_status": "PENDING",
    }
    assert by_id[str(child_a.id)] == {
        "id": str(child_a.id),
        "name": "Child A",
        "role": "child",
        "activation_status": "PENDING",
    }
    assert by_id[str(child_b.id)] == {
        "id": str(child_b.id),
        "name": "Child B",
        "role": "child",
        "activation_status": "PENDING",
    }


# --- Child cannot discover users --------------------------------------------------------


def test_child_cannot_discover_users(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.get("/api/users", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- Current Adult is included ----------------------------------------------------------


def test_current_adult_is_included_in_results(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT, "Solo Adult")

    response = client.get("/api/users", headers=auth(adult))

    assert response.status_code == 200
    ids = [entry["id"] for entry in response.json()]
    assert str(adult.id) in ids


# --- Both roles are returned, no implicit filtering -------------------------------------


def test_response_includes_both_adult_and_child_roles(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.get("/api/users", headers=auth(adult))

    roles = {entry["role"] for entry in response.json()}
    assert roles == {"adult", "child"}
    ids = {entry["id"] for entry in response.json()}
    assert {str(adult.id), str(child.id)} <= ids


# --- Deterministic ordering ---------------------------------------------------------------


def test_users_are_ordered_by_name_then_id(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    charlie = make_user(ADULT, "Charlie")
    alice = make_user(ADULT, "Alice")
    make_user(CHILD, "Bob")

    response = client.get("/api/users", headers=auth(charlie))

    body = response.json()
    assert [entry["name"] for entry in body] == ["Alice", "Bob", "Charlie"]
    assert body[0]["id"] == str(alice.id)


def test_users_with_equal_names_are_ordered_by_id(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT, "Requester")
    first = make_user(CHILD, "Alice")
    second = make_user(CHILD, "Alice")
    expected_order = sorted([first.id, second.id], key=str)

    response = client.get("/api/users", headers=auth(adult))

    alice_ids_in_order = [entry["id"] for entry in response.json() if entry["name"] == "Alice"]
    assert alice_ids_in_order == [str(uid) for uid in expected_order]


# --- Empty collection ----------------------------------------------------------------------

# Not testable under the current identity model: GET /api/users requires a valid
# session, which in turn requires an existing, authenticated Adult (via
# get_current_user + require_adult), so a successful request is only possible
# once at least one User (the requesting Adult) already exists. A genuinely
# empty result set therefore cannot occur for any request that passes
# authentication -- there is no artificial-behavior path to test here.


# --- Error contract (existing identity behavior, reused as-is) -----------------------------


def test_missing_identity_header_rejected(client: TestClient) -> None:
    response = client.get("/api/users")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/users", headers={"X-User-Id": str(adult.id)})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# =========================================================================================
# User creation (Issue #8)
# =========================================================================================

# --- Authorization -------------------------------------------------------------------------


def test_adult_can_create_a_child(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "New Child", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 201
    assert response.json()["role"] == "child"


def test_adult_can_create_an_adult(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "New Adult", "role": "adult"}, headers=auth(adult)
    )

    assert response.status_code == 201
    assert response.json()["role"] == "adult"


def test_child_cannot_create_a_child(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(
        "/api/users", json={"name": "New Child", "role": "child"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_child_cannot_create_an_adult(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(
        "/api/users", json={"name": "New Adult", "role": "adult"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_create_missing_identity_header_rejected(client: TestClient) -> None:
    response = client.post("/api/users", json={"name": "New User", "role": "child"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_create_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users",
        json={"name": "New User", "role": "child"},
        headers={"X-User-Id": str(adult.id)},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# --- Creation --------------------------------------------------------------------------------


def test_successful_creation_returns_generated_fields(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["name"] == "Alice"
    assert body["role"] == "child"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


def test_created_user_is_persisted_in_the_database(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult)
    )

    created_id = uuid.UUID(response.json()["id"])
    stored = db_session.get(User, created_id)
    assert stored is not None
    assert stored.name == "Alice"
    assert stored.role == CHILD


def test_created_user_appears_via_get_users(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    created = client.post(
        "/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult)
    ).json()

    response = client.get("/api/users", headers=auth(adult))

    ids = [entry["id"] for entry in response.json()]
    assert created["id"] in ids


# --- Validation --------------------------------------------------------------------------------


def test_missing_name_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post("/api/users", json={"role": "child"}, headers=auth(adult))

    assert response.status_code == 422


def test_empty_name_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post("/api/users", json={"name": "", "role": "child"}, headers=auth(adult))

    assert response.status_code == 422


def test_whitespace_only_name_returns_422(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "   \t\n", "role": "child"}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_missing_role_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post("/api/users", json={"name": "Alice"}, headers=auth(adult))

    assert response.status_code == 422


def test_invalid_role_returns_422(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users", json={"name": "Alice", "role": "grandparent"}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_duplicate_names_are_allowed(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    first = client.post("/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult))
    second = client.post("/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


# --- Input protection --------------------------------------------------------------------------


def test_client_cannot_choose_the_user_id(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    requested_id = str(uuid.uuid4())

    response = client.post(
        "/api/users",
        json={"id": requested_id, "name": "Alice", "role": "child"},
        headers=auth(adult),
    )

    assert response.status_code == 201
    assert response.json()["id"] != requested_id


def test_client_cannot_set_created_at(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users",
        json={"name": "Alice", "role": "child", "created_at": "2000-01-01T00:00:00Z"},
        headers=auth(adult),
    )

    assert response.status_code == 201
    assert not response.json()["created_at"].startswith("2000-01-01")


def test_client_cannot_set_updated_at(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users",
        json={"name": "Alice", "role": "child", "updated_at": "2000-01-01T00:00:00Z"},
        headers=auth(adult),
    )

    assert response.status_code == 201
    assert not response.json()["updated_at"].startswith("2000-01-01")


def test_created_by_field_does_not_exist(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/users",
        json={"name": "Alice", "role": "child", "created_by": str(adult.id)},
        headers=auth(adult),
    )

    assert response.status_code == 201
    assert "created_by" not in response.json()


# --- Integration: creation -> discovery -> task assignment --------------------------------------


def test_new_user_integrates_with_discovery_and_task_assignment(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    created = client.post(
        "/api/users", json={"name": "Fresh Child", "role": "child"}, headers=auth(adult)
    ).json()
    child_id = created["id"]
    # POST /api/users creates a domain User plus an activation token (Issue
    # #10) -- but no credentials or session until that token is actually used
    # via POST /api/auth/activate. Fetch the row so `auth()` can issue this
    # new User a real session for the rest of the flow, exactly as their own
    # future activation+login would.
    child = db_session.get(User, uuid.UUID(child_id))
    assert child is not None

    discovered = client.get("/api/users", headers=auth(adult)).json()
    assert child_id in [entry["id"] for entry in discovered]

    task = client.post(
        "/api/tasks",
        json={"title": "Tidy up", "assigned_to": child_id, "reward_points": 10},
        headers=auth(adult),
    ).json()

    executions = client.get("/api/task-executions", headers=auth(child)).json()
    execution = next(e for e in executions if e["task_id"] == task["id"])
    assert execution["user_id"] == child_id
    assert execution["status"] == "ASSIGNED"

    start = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    assert start.status_code == 200
    assert start.json()["status"] == "IN_PROGRESS"

    balance = client.get("/api/points/balance", headers=auth(child))
    assert balance.status_code == 200
    assert balance.json() == {"balance": 0}


# --- User creation -> activation atomicity (Issue #10) -------------------------------------


def test_user_and_activation_creation_is_transactional(db_session: Session) -> None:
    """Mirrors test_setup_is_transactional (test_auth.py): forces a real DB
    constraint violation partway through the same sequence create_user()
    performs (User insert, flush, UserActivation insert, one commit), and
    asserts neither the User nor the activation survives.
    """
    existing = User(name="Existing", role=CHILD)
    db_session.add(existing)
    db_session.commit()
    db_session.add(
        UserActivation(
            user_id=existing.id,
            token_hash=hash_token("existing-token"),
            expires_at=utcnow() + timedelta(hours=72),
        )
    )
    db_session.commit()

    new_user_id = uuid.uuid4()
    db_session.add(User(id=new_user_id, name="New Child", role=CHILD))
    db_session.flush()
    db_session.add(
        UserActivation(
            user_id=existing.id,  # duplicate -> unique constraint violation on user_id
            token_hash=hash_token("new-token"),
            expires_at=utcnow() + timedelta(hours=72),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(User, new_user_id) is None


# =========================================================================================
# Activation status on GET /api/users (Issue #16)
# =========================================================================================


def test_active_user_is_reported_as_active(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "active@example.com")

    response = client.get("/api/users", headers=auth(adult))

    body = {entry["id"]: entry for entry in response.json()}
    assert body[str(adult.id)]["activation_status"] == "ACTIVE"


def test_user_without_credentials_is_reported_as_pending(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.get("/api/users", headers=auth(adult))

    body = {entry["id"]: entry for entry in response.json()}
    assert body[str(child.id)]["activation_status"] == "PENDING"


def test_activation_status_never_exposes_email_or_token_fields(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    create_credential(db_session, adult, "active@example.com")
    child = make_user(CHILD)
    create_activation(child)

    response = client.get("/api/users", headers=auth(adult))

    for entry in response.json():
        assert set(entry.keys()) == {"id", "name", "role", "activation_status"}


# =========================================================================================
# Activation regeneration: POST /api/users/{id}/activation (Issue #16)
# =========================================================================================


def test_adult_can_regenerate_activation_for_a_pending_user(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_activation(child)

    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["activation_token"], str)
    assert body["activation_token"]
    assert "expires_at" in body


def test_regenerated_token_hash_matches_response_and_reuses_the_existing_row(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_activation(child)
    existing = db_session.scalar(select(UserActivation).where(UserActivation.user_id == child.id))
    assert existing is not None
    existing_id = existing.id

    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    row_count = db_session.scalar(
        select(func.count()).select_from(UserActivation).where(UserActivation.user_id == child.id)
    )
    assert row_count == 1
    activation = db_session.scalar(select(UserActivation).where(UserActivation.user_id == child.id))
    assert activation is not None
    assert activation.id == existing_id  # same row reused, not a new one
    assert activation.token_hash == hash_token(response.json()["activation_token"])


def test_new_token_activates_and_previous_token_no_longer_works(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    old_token = create_activation(child)

    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))
    new_token = response.json()["activation_token"]

    old_attempt = client.post(
        "/api/auth/activate",
        json={"token": old_token, "email": "kid@example.com", "password": PASSWORD},
    )
    assert old_attempt.status_code == 400
    assert old_attempt.json()["error"]["code"] == "INVALID_ACTIVATION_TOKEN"

    new_attempt = client.post(
        "/api/auth/activate",
        json={"token": new_token, "email": "kid@example.com", "password": PASSWORD},
    )
    assert new_attempt.status_code == 200
    assert new_attempt.json()["id"] == str(child.id)


def test_new_expiration_is_approximately_72_hours_from_regeneration(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_activation(child, expires_in=timedelta(hours=1))  # about to expire

    before = utcnow()
    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))
    after = utcnow()

    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    assert before + timedelta(hours=72) - timedelta(seconds=5) <= expires_at
    assert expires_at <= after + timedelta(hours=72) + timedelta(seconds=5)


def test_regenerating_resets_used_at_to_null(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    """A pending (credential-less) User can never actually reach a real
    used_at-is-set state through the API (that only happens together with
    credential creation, which would make them ACTIVE, not PENDING) -- this
    directly manipulates the row to prove regenerate() unconditionally
    clears used_at, matching its documented contract.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_activation(child)
    activation = db_session.scalar(select(UserActivation).where(UserActivation.user_id == child.id))
    assert activation is not None
    activation.used_at = utcnow()
    db_session.commit()

    client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    db_session.refresh(activation)
    assert activation.used_at is None


def test_regenerating_an_active_user_returns_409(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_credential(db_session, child, "kid@example.com")

    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_ALREADY_ACTIVATED"


def test_regenerating_an_active_user_does_not_touch_their_credentials(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    credential = create_credential(db_session, child, "kid@example.com")

    client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    db_session.refresh(credential)
    assert credential.email == "kid@example.com"


def test_regenerating_an_unknown_user_returns_404(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(f"/api/users/{uuid.uuid4()}/activation", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


def test_child_cannot_regenerate_activation(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    create_activation(other_child)

    response = client.post(f"/api/users/{other_child.id}/activation", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_unauthenticated_cannot_regenerate_activation(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)
    create_activation(child)

    response = client.post(f"/api/users/{child.id}/activation")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_regeneration_does_not_create_a_second_activation_row(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_activation(child)

    client.post(f"/api/users/{child.id}/activation", headers=auth(adult))
    client.post(f"/api/users/{child.id}/activation", headers=auth(adult))
    client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    row_count = db_session.scalar(
        select(func.count()).select_from(UserActivation).where(UserActivation.user_id == child.id)
    )
    assert row_count == 1


def test_activating_then_regenerating_is_rejected_because_the_user_is_now_active(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    token = create_activation(child)
    client.post(
        "/api/auth/activate",
        json={"token": token, "email": "kid@example.com", "password": PASSWORD},
    )

    response = client.post(f"/api/users/{child.id}/activation", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_ALREADY_ACTIVATED"


# --- Concurrency ---------------------------------------------------------------------------


def test_concurrent_regeneration_leaves_exactly_one_row_and_one_current_token() -> None:
    """Exercises two genuinely independent, concurrently-committing sessions
    (not the shared savepoint-isolated db_session/client fixtures) against
    the same pending User's activation row -- mirrors the redemption
    concurrency test pattern (Issue #6/#12). A plain UPDATE-by-unique-key on
    the same row is expected to serialize safely under Postgres's normal
    row-level locking; this proves no second row is created and the row
    left behind matches exactly one of the two returned tokens.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    setup_session.add(adult)
    setup_session.commit()
    setup_session.refresh(adult)

    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add(child)
    setup_session.commit()
    setup_session.refresh(child)

    setup_session.add(
        UserActivation(
            user_id=child.id,
            token_hash=hash_token("initial-token"),
            expires_at=utcnow() + timedelta(hours=72),
        )
    )
    setup_session.commit()

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: list[tuple[int, str | None]] = []
        barrier = threading.Barrier(2)

        def attempt_regenerate() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/users/{child.id}/activation", headers=auth_headers
                )
            token = response.json().get("activation_token") if response.status_code == 200 else None
            results.append((response.status_code, token))

        threads = [threading.Thread(target=attempt_regenerate) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert [status for status, _ in results] == [200, 200]

        row_count = setup_session.scalar(
            select(func.count())
            .select_from(UserActivation)
            .where(UserActivation.user_id == child.id)
        )
        assert row_count == 1

        final_activation = setup_session.scalar(
            select(UserActivation).where(UserActivation.user_id == child.id)
        )
        assert final_activation is not None
        returned_tokens = {token for _, token in results if token is not None}
        matching = [t for t in returned_tokens if hash_token(t) == final_activation.token_hash]
        assert len(matching) == 1
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(UserActivation).filter_by(user_id=child.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()
