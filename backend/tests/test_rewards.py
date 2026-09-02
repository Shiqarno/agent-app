import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models import User, UserRole

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def auth(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


def create_reward(client: TestClient, adult: User, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"name": "Extra gaming hour", "cost_points": 100}
    payload.update(overrides)
    response = client.post("/api/rewards", json=payload, headers=auth(adult))
    return response.json()


# --- Read ---------------------------------------------------------------------------


def test_adult_can_retrieve_the_global_catalog(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    create_reward(client, adult, name="Reward A")

    response = client.get("/api/rewards", headers=auth(adult))

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_child_can_retrieve_the_global_catalog(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    create_reward(client, adult, name="Reward A")

    response = client.get("/api/rewards", headers=auth(child))

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_all_rewards_are_returned(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    create_reward(client, adult, name="Reward A")
    create_reward(client, adult, name="Reward B")
    create_reward(client, adult, name="Reward C")

    response = client.get("/api/rewards", headers=auth(adult))

    assert len(response.json()) == 3


def test_rewards_are_not_filtered_by_created_by(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    create_reward(client, adult_a, name="From A")
    create_reward(client, adult_b, name="From B")

    response_as_a = client.get("/api/rewards", headers=auth(adult_a))
    response_as_b = client.get("/api/rewards", headers=auth(adult_b))

    names_as_a = {r["name"] for r in response_as_a.json()}
    names_as_b = {r["name"] for r in response_as_b.json()}
    assert names_as_a == names_as_b == {"From A", "From B"}


def test_catalog_ordering_is_deterministic(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    create_reward(client, adult, name="Charlie")
    create_reward(client, adult, name="Alice")
    create_reward(client, adult, name="Bob")

    response = client.get("/api/rewards", headers=auth(adult))

    assert [r["name"] for r in response.json()] == ["Alice", "Bob", "Charlie"]


def test_catalog_ordering_ties_broken_by_id(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    first = create_reward(client, adult, name="Same Name")
    second = create_reward(client, adult, name="Same Name")
    expected_order = sorted([str(first["id"]), str(second["id"])])

    response = client.get("/api/rewards", headers=auth(adult))

    ids = [r["id"] for r in response.json() if r["name"] == "Same Name"]
    assert ids == expected_order


def test_empty_catalog_returns_200_empty_list(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/rewards", headers=auth(adult))

    assert response.status_code == 200
    assert response.json() == []


# --- Create ---------------------------------------------------------------------------


def test_adult_can_create_a_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/rewards",
        json={
            "name": "Extra gaming hour",
            "description": "One additional hour of gaming",
            "cost_points": 100,
        },
        headers=auth(adult),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Extra gaming hour"
    assert body["description"] == "One additional hour of gaming"
    assert body["cost_points"] == 100


def test_created_by_is_set_to_the_current_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    reward = create_reward(client, adult)

    assert reward["created_by"] == str(adult.id)


def test_child_cannot_create_a_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(
        "/api/rewards", json={"name": "Reward", "cost_points": 10}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_missing_identity_header_rejected_on_create(client: TestClient) -> None:
    response = client.post("/api/rewards", json={"name": "Reward", "cost_points": 10})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_zero_cost_points_is_rejected(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/rewards", json={"name": "Reward", "cost_points": 0}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_negative_cost_points_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/rewards", json={"name": "Reward", "cost_points": -1}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_empty_name_is_rejected(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/rewards", json={"name": "   ", "cost_points": 10}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_client_cannot_set_created_by(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")

    response = client.post(
        "/api/rewards",
        json={"name": "Reward", "cost_points": 10, "created_by": str(other_adult.id)},
        headers=auth(adult),
    )

    assert response.status_code == 201
    assert response.json()["created_by"] == str(adult.id)


# --- Update -----------------------------------------------------------------------------


def test_adult_can_modify_a_reward_created_by_another_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    reward = create_reward(client, creator, name="Original")

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"name": "Renamed"}, headers=auth(other_adult)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["created_by"] == str(creator.id)


def test_adult_can_modify_the_name(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult, name="Original")

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"name": "Updated"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated"


def test_adult_can_modify_the_description(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult, description="Old description")

    response = client.patch(
        f"/api/rewards/{reward['id']}",
        json={"description": "New description"},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["description"] == "New description"


def test_adult_can_modify_the_cost(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult, cost_points=100)

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"cost_points": 150}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["cost_points"] == 150


def test_update_only_changes_provided_fields(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(
        client, adult, name="Original", description="Original description", cost_points=100
    )

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"cost_points": 150}, headers=auth(adult)
    )

    body = response.json()
    assert body["name"] == "Original"
    assert body["description"] == "Original description"
    assert body["cost_points"] == 150


def test_child_cannot_modify_a_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    reward = create_reward(client, adult)

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"name": "Hacked"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_updating_unknown_reward_returns_404(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.patch(
        f"/api/rewards/{uuid.uuid4()}", json={"name": "Updated"}, headers=auth(adult)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REWARD_NOT_FOUND"


def test_created_by_cannot_be_changed_via_update(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    reward = create_reward(client, creator)

    response = client.patch(
        f"/api/rewards/{reward['id']}",
        json={"name": "Updated", "created_by": str(other_adult.id)},
        headers=auth(creator),
    )

    assert response.status_code == 200
    assert response.json()["created_by"] == str(creator.id)


def test_updated_at_changes_after_a_successful_update(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult)

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"name": "Updated"}, headers=auth(adult)
    )

    assert response.json()["updated_at"] != reward["updated_at"]


def test_update_rejects_zero_cost_points(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult)

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"cost_points": 0}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_update_rejects_blank_name(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult)

    response = client.patch(
        f"/api/rewards/{reward['id']}", json={"name": "   "}, headers=auth(adult)
    )

    assert response.status_code == 422
