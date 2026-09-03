import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db import SessionLocal
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import PointTransaction, Task, TaskStatus, User, UserRole, UserSession, utcnow

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


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


def test_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/tasks", headers={"X-User-Id": str(adult.id)})

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


# =========================================================================================
# Task Details: GET /api/tasks/{id} (Issue #17)
# =========================================================================================


def test_creator_can_retrieve_their_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.get(f"/api/tasks/{task['id']}", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]


def test_assignee_can_retrieve_their_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.get(f"/api/tasks/{task['id']}", headers=auth(child))

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]


def test_unrelated_user_cannot_retrieve_the_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult, child)

    response = client.get(f"/api/tasks/{task['id']}", headers=auth(other_adult))

    # Existence is not leaked to a user who is neither creator nor assignee.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_unauthenticated_cannot_retrieve_a_task(client: TestClient) -> None:
    response = client.get(f"/api/tasks/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_task_returns_404_for_details(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get(f"/api/tasks/{uuid.uuid4()}", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


# =========================================================================================
# Task Editing: PATCH /api/tasks/{id} (Issue #17)
# =========================================================================================


def test_creator_can_edit_title_while_assigned(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, title="Old title")

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "New title"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["title"] == "New title"


def test_creator_can_edit_description_while_assigned(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"description": "New description"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["description"] == "New description"


def test_edit_updates_updated_at(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    original_updated_at = task["updated_at"]

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Updated"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["updated_at"] != original_updated_at


def test_assignee_cannot_edit_the_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Hijacked"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_other_users_cannot_edit_the_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult, child)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Hijacked"}, headers=auth(other_adult)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_edit_is_rejected_in_in_progress(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Too late"}, headers=auth(adult)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_edit_is_rejected_in_awaiting_confirmation(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Too late"}, headers=auth(adult)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_edit_is_rejected_for_completed_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Too late"}, headers=auth(adult)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_edit_is_rejected_for_cancelled_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Too late"}, headers=auth(adult)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_reward_points_cannot_be_changed_through_update(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=5)

    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "New title", "reward_points": 999},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["reward_points"] == 5


def test_assignment_cannot_be_changed_through_update(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "New title", "assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(child.id)


# =========================================================================================
# Reassignment: POST /api/tasks/{id}/reassign (Issue #17)
# =========================================================================================


def test_creator_can_reassign_an_assigned_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(other_child.id)


def test_reassign_target_user_must_exist(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(uuid.uuid4())},
        headers=auth(adult),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_FOUND"


def test_reassignment_keeps_status_assigned(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.json()["status"] == "ASSIGNED"


def test_reassignment_updates_updated_at(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.json()["updated_at"] != task["updated_at"]


def test_assignee_cannot_reassign(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(child),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_other_users_cannot_reassign(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_adult.id)},
        headers=auth(other_adult),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_reassignment_is_rejected_after_execution_begins(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_reassignment_is_rejected_for_terminal_states(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_reassignment_to_self_works(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(adult.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(adult.id)


def test_reassignment_to_adult_works(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_adult.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(other_adult.id)


def test_reassignment_to_child_works(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_task(client, adult, child)

    response = client.post(
        f"/api/tasks/{task['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["assigned_to"] == str(other_child.id)


# =========================================================================================
# Cancellation: POST /api/tasks/{id}/cancel (Issue #17)
# =========================================================================================


def test_creator_can_cancel_an_assigned_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_creator_can_cancel_an_in_progress_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_creator_can_cancel_an_awaiting_confirmation_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancellation_updates_updated_at(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.json()["updated_at"] != task["updated_at"]


def test_assignee_cannot_cancel(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_other_users_cannot_cancel(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(other_adult))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_completed_task_cannot_be_cancelled(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cancelled_task_cannot_be_cancelled_again(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    response = client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cancellation_creates_no_point_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    client.post(f"/api/tasks/{task['id']}/cancel", headers=auth(adult))

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.task_id == uuid.UUID(task["id"]))
    )
    assert count == 0


# =========================================================================================
# Lifecycle regression (Issue #17 must not change existing behavior)
# =========================================================================================


def test_confirm_still_creates_exactly_one_task_completion_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=15)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    transactions = list(
        db_session.scalars(
            select(PointTransaction).where(PointTransaction.task_id == uuid.UUID(task["id"]))
        )
    )
    assert len(transactions) == 1
    assert transactions[0].amount == 15
    assert transactions[0].reason.value == "TASK_COMPLETED"


# =========================================================================================
# Concurrency (Issue #17)
# =========================================================================================


def real_session_headers(session: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Like conftest.auth(), but against an explicitly supplied, real,
    independently-committing session -- for the concurrency tests below,
    which intentionally bypass the shared savepoint-isolated db_session
    fixture.
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


def test_concurrent_confirm_and_cancel_cannot_both_succeed() -> None:
    """The contradictory-transition scenario Issue #17 explicitly calls out:
    a Task in AWAITING_CONFIRMATION racing between the creator's confirm and
    the creator's cancel must not end up COMPLETED-with-no-points-side-
    effect-missing nor CANCELLED-with-a-stray-TASK_COMPLETED-transaction.
    Exactly one request must win; the loser must see a real rejection.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(
        title="Race me",
        reward_points=25,
        status=TaskStatus.AWAITING_CONFIRMATION,
        assigned_to=child.id,
        created_by=adult.id,
    )
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: dict[str, int] = {}
        barrier = threading.Barrier(2)

        def attempt(action: str) -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/tasks/{task.id}/{action}", headers=auth_headers
                )
            results[action] = response.status_code

        threads = [
            threading.Thread(target=attempt, args=("confirm",)),
            threading.Thread(target=attempt, args=("cancel",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results.values()) == [200, 409]

        setup_session.expire_all()
        final_task = setup_session.get(Task, task.id)
        assert final_task is not None
        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_id == task.id)
        )

        if results["confirm"] == 200:
            assert final_task.status == TaskStatus.COMPLETED
            assert transaction_count == 1
        else:
            assert final_task.status == TaskStatus.CANCELLED
            assert transaction_count == 0
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(PointTransaction).filter_by(task_id=task.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


def test_concurrent_cancel_requests_leave_exactly_one_terminal_transition() -> None:
    """Two simultaneous cancel requests on the same Task must not both
    report success -- the row lock serializes them, so the second sees the
    already-CANCELLED status and is correctly rejected.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult 2", role=ADULT)
    child = User(name="Concurrent Child 2", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(
        title="Cancel race",
        reward_points=10,
        status=TaskStatus.ASSIGNED,
        assigned_to=child.id,
        created_by=adult.id,
    )
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def attempt_cancel() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(f"/api/tasks/{task.id}/cancel", headers=auth_headers)
            results.append(response.status_code)

        threads = [threading.Thread(target=attempt_cancel) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [200, 409]

        setup_session.expire_all()
        final_task = setup_session.get(Task, task.id)
        assert final_task is not None
        assert final_task.status == TaskStatus.CANCELLED
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()
