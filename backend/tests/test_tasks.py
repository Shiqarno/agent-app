import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models import User, UserRole

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def auth(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


def create_task(
    client: TestClient, adult: User, child: User, **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {"title": "Task", "child_id": str(child.id), "reward_points": 5}
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload, headers=auth(adult))
    return response.json()


# --- AC1: Adult creates a task ---------------------------------------------------


def test_adult_creates_task_with_status_assigned(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT, "Adult A")
    child = make_user(CHILD, "Child A")

    response = client.post(
        "/api/tasks",
        json={
            "title": "Clean room",
            "description": "Tidy up",
            "child_id": str(child.id),
            "reward_points": 10,
        },
        headers=auth(adult),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ASSIGNED"
    assert body["title"] == "Clean room"
    assert body["description"] == "Tidy up"
    assert body["child_id"] == str(child.id)
    assert body["adult_id"] == str(adult.id)
    assert body["reward_points"] == 10


# --- AC2 / AC3: task visibility ---------------------------------------------------


def test_child_sees_assigned_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    created = create_task(client, adult, child)

    response = client.get("/api/tasks", headers=auth(child))

    assert response.status_code == 200
    ids = [task["id"] for task in response.json()]
    assert created["id"] in ids


def test_child_cannot_see_another_childs_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    create_task(client, adult, child_a)

    response = client.get("/api/tasks", headers=auth(child_b))

    assert response.status_code == 200
    assert response.json() == []


def test_adult_sees_only_own_created_tasks(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    child = make_user(CHILD)
    create_task(client, adult_a, child)

    response = client.get("/api/tasks", headers=auth(adult_b))

    assert response.status_code == 200
    assert response.json() == []


# --- AC4 / AC5: starting a task ---------------------------------------------------


def test_child_starts_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_child_cannot_start_another_childs_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = create_task(client, adult, child_a)

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get("/api/tasks", headers=auth(child_a)).json()
    assert unchanged[0]["status"] == "ASSIGNED"


# --- AC6: marking a task ready -----------------------------------------------------


def test_child_marks_task_ready(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    assert response.status_code == 200
    assert response.json()["status"] == "AWAITING_CONFIRMATION"


# --- AC7: child cannot confirm ------------------------------------------------------


def test_child_cannot_confirm_completion(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get("/api/tasks", headers=auth(child)).json()
    assert unchanged[0]["status"] == "AWAITING_CONFIRMATION"


# --- AC8 / AC9: confirming completion -----------------------------------------------


def test_adult_confirms_completion(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_another_adult_cannot_confirm_completion(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    child = make_user(CHILD)
    task = create_task(client, adult_a, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get("/api/tasks", headers=auth(adult_a)).json()
    assert unchanged[0]["status"] == "AWAITING_CONFIRMATION"


# --- AC10: invalid state transitions rejected ---------------------------------------


def test_cannot_mark_ready_before_starting(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_confirm_before_ready(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_start_task_twice(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_transition_a_completed_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


# --- AC11: completion does not award points -----------------------------------------


def test_task_completion_has_no_points_side_effect(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=42)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert response.status_code == 200
    inspector = inspect(db_session.get_bind())
    assert set(inspector.get_table_names()) == {"alembic_version", "projects", "users", "tasks"}


# --- Task creation validation ---------------------------------------------------------


def test_create_task_missing_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks", json={"child_id": str(child.id), "reward_points": 5}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_blank_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "   ", "child_id": str(child.id), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_missing_child(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks", json={"title": "Task", "reward_points": 5}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_missing_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks", json={"title": "Task", "child_id": str(child.id)}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_zero_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "child_id": str(child.id), "reward_points": 0},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_negative_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "child_id": str(child.id), "reward_points": -1},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_nonexistent_child(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "child_id": str(uuid.uuid4()), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CHILD_NOT_FOUND"


def test_create_task_child_id_is_actually_an_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "child_id": str(other_adult.id), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CHILD_NOT_FOUND"


def test_child_cannot_create_task(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "child_id": str(other_child.id), "reward_points": 5},
        headers=auth(child),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- Identity edge cases ---------------------------------------------------------------


def test_missing_identity_header_rejected(client: TestClient) -> None:
    response = client.get("/api/tasks")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_user_id_rejected(client: TestClient) -> None:
    response = client.get("/api/tasks", headers={"X-User-Id": str(uuid.uuid4())})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_task_not_found_for_start(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(f"/api/tasks/{uuid.uuid4()}/start", headers=auth(child))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_task_not_found_for_confirm(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(f"/api/tasks/{uuid.uuid4()}/confirm", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"
