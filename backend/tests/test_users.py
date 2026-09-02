import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models import User, UserRole

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def auth(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


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
# X-User-Id resolving to an existing Adult (via get_current_user + require_adult),
# so a successful request is only possible once at least one User (the requesting
# Adult) already exists. A genuinely empty result set therefore cannot occur for
# any request that passes authentication -- there is no artificial-behavior path
# to test here.


# --- Error contract (existing identity behavior, reused as-is) -----------------------------


def test_missing_identity_header_rejected(client: TestClient) -> None:
    response = client.get("/api/users")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_user_id_rejected(client: TestClient) -> None:
    response = client.get("/api/users", headers={"X-User-Id": str(uuid.uuid4())})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
