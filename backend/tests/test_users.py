import uuid
from collections.abc import Callable

from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, UserRole

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


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
    assert by_id[str(adult_a.id)] == {"id": str(adult_a.id), "name": "Adult A", "role": "adult"}
    assert by_id[str(adult_b.id)] == {"id": str(adult_b.id), "name": "Adult B", "role": "adult"}
    assert by_id[str(child_a.id)] == {"id": str(child_a.id), "name": "Child A", "role": "child"}
    assert by_id[str(child_b.id)] == {"id": str(child_b.id), "name": "Child B", "role": "child"}


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

    alice_ids_in_order = [
        entry["id"] for entry in response.json() if entry["name"] == "Alice"
    ]
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

    response = client.post(
        "/api/users", json={"name": "", "role": "child"}, headers=auth(adult)
    )

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

    first = client.post(
        "/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult)
    )
    second = client.post(
        "/api/users", json={"name": "Alice", "role": "child"}, headers=auth(adult)
    )

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
    # POST /api/users creates a domain User only -- no credentials, no session
    # (Issue #10 territory). Fetch the row so `auth()` can issue this new
    # User a real session for the rest of the flow, exactly as their own
    # future login would.
    child = db_session.get(User, uuid.UUID(child_id))
    assert child is not None

    discovered = client.get("/api/users", headers=auth(adult)).json()
    assert child_id in [entry["id"] for entry in discovered]

    task = client.post(
        "/api/tasks",
        json={"title": "Tidy up", "assigned_to": child_id, "reward_points": 10},
        headers=auth(adult),
    ).json()
    assert task["assigned_to"] == child_id
    assert task["status"] == "ASSIGNED"

    start = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    assert start.status_code == 200
    assert start.json()["status"] == "IN_PROGRESS"

    balance = client.get("/api/points/balance", headers=auth(child))
    assert balance.status_code == 200
    assert balance.json() == {"balance": 0}
