import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models import User, UserRole

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def auth(user: User) -> dict[str, str]:
    return {"X-User-Id": str(user.id)}


def create_task(
    client: TestClient, creator: User, assignee: User, **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Task",
        "assigned_to": str(assignee.id),
        "reward_points": 5,
    }
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload, headers=auth(creator))
    return response.json()


# --- AC1 / AC2 / AC3: Adult assigns to Child, another Adult, or themselves ------------


def test_adult_assigns_task_to_child(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT, "Adult A")
    child = make_user(CHILD, "Child A")

    response = client.post(
        "/api/tasks",
        json={
            "title": "Clean room",
            "description": "Tidy up",
            "assigned_to": str(child.id),
            "reward_points": 10,
        },
        headers=auth(adult),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ASSIGNED"
    assert body["title"] == "Clean room"
    assert body["description"] == "Tidy up"
    assert body["assigned_to"] == str(child.id)
    assert body["created_by"] == str(adult.id)
    assert body["reward_points"] == 10


def test_adult_assigns_task_to_another_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(adult_b.id), "reward_points": 10},
        headers=auth(adult_a),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ASSIGNED"
    assert body["assigned_to"] == str(adult_b.id)
    assert body["created_by"] == str(adult_a.id)


def test_adult_assigns_task_to_self(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(adult.id), "reward_points": 10},
        headers=auth(adult),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ASSIGNED"
    assert body["created_by"] == str(adult.id)
    assert body["assigned_to"] == str(adult.id)


# --- AC4 / AC5: assigned Adult can start and mark ready -------------------------------


def test_assigned_adult_can_start_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a, adult_b)

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult_b))

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_assigned_adult_can_mark_task_ready(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a, adult_b)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult_b))

    response = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(adult_b))

    assert response.status_code == 200
    assert response.json()["status"] == "AWAITING_CONFIRMATION"


# --- AC6: creator confirms a task assigned to another Adult ---------------------------


def test_creator_confirms_task_assigned_to_another_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a, adult_b)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult_b))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(adult_b))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult_a))

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


# --- AC7: full self-assigned lifecycle -------------------------------------------------


def test_self_assigned_task_can_complete_full_lifecycle(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult, adult)

    start = client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult))
    assert start.json()["status"] == "IN_PROGRESS"

    ready = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(adult))
    assert ready.json()["status"] == "AWAITING_CONFIRMATION"

    confirm = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "COMPLETED"


# --- AC8: Child assignment remains valid -----------------------------------------------


def test_child_assignment_lifecycle_still_works(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    ready = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))
    assert ready.json()["status"] == "AWAITING_CONFIRMATION"

    confirm = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "COMPLETED"


# --- AC9: Child cannot create a task ----------------------------------------------------


def test_child_cannot_create_task(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(other_child.id), "reward_points": 5},
        headers=auth(child),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- AC10: non-assignee cannot start/mark ready, regardless of role -------------------


def test_non_assignee_adult_cannot_start_another_adults_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    adult_c = make_user(ADULT, "Adult C")
    task = create_task(client, adult_a, adult_b)

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult_c))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get("/api/tasks", headers=auth(adult_b)).json()
    assert unchanged[0]["status"] == "ASSIGNED"


def test_non_assignee_child_cannot_start_another_childs_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = create_task(client, adult, child_a)

    response = client.post(f"/api/tasks/{task['id']}/start", headers=auth(child_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_non_assignee_cannot_mark_task_ready(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = create_task(client, adult, child_a)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child_a))

    response = client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- AC11: non-creator cannot confirm, even the assignee -------------------------------


def test_assignee_cannot_confirm_their_own_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a, adult_b)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(adult_b))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(adult_b))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get("/api/tasks", headers=auth(adult_a)).json()
    assert unchanged[0]["status"] == "AWAITING_CONFIRMATION"


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


# --- AC12: nonexistent assignee rejected ------------------------------------------------


def test_create_task_nonexistent_assignee(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(uuid.uuid4()), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_FOUND"


# --- AC13 / AC14: task visibility, including self-assignment dedup ---------------------


def test_task_visible_to_both_creator_and_assignee(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    adult_c = make_user(ADULT, "Adult C")
    task = create_task(client, adult_a, adult_b)

    creator_view = client.get("/api/tasks", headers=auth(adult_a)).json()
    assert task["id"] in [t["id"] for t in creator_view]

    assignee_view = client.get("/api/tasks", headers=auth(adult_b)).json()
    assert task["id"] in [t["id"] for t in assignee_view]

    unrelated_view = client.get("/api/tasks", headers=auth(adult_c)).json()
    assert task["id"] not in [t["id"] for t in unrelated_view]


def test_self_assigned_task_is_not_duplicated_in_list(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult, adult)

    response = client.get("/api/tasks", headers=auth(adult))

    matches = [t for t in response.json() if t["id"] == task["id"]]
    assert len(matches) == 1


def test_child_still_cannot_see_another_childs_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    create_task(client, adult, child_a)

    response = client.get("/api/tasks", headers=auth(child_b))

    assert response.status_code == 200
    assert response.json() == []


# --- AC15: invalid state transitions remain rejected ------------------------------------


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


# Note: the "completion has no points side effect" invariant from Issue #1/#2
# is intentionally superseded by Issue #3 (Point Ledger) -- see tests/test_points.py,
# which now covers the (correct, current) point-awarding behavior on confirmation.


# --- Task creation validation ---------------------------------------------------------


def test_create_task_missing_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"assigned_to": str(child.id), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_blank_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "   ", "assigned_to": str(child.id), "reward_points": 5},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_missing_assignee(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks", json={"title": "Task", "reward_points": 5}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_missing_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks", json={"title": "Task", "assigned_to": str(child.id)}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_zero_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(child.id), "reward_points": 0},
        headers=auth(adult),
    )

    assert response.status_code == 422


def test_create_task_negative_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks",
        json={"title": "Task", "assigned_to": str(child.id), "reward_points": -1},
        headers=auth(adult),
    )

    assert response.status_code == 422


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
