import hashlib
import secrets
import threading
import time
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
from app.models import Task, TaskExecution, User, UserRole, UserSession, utcnow

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def create_task(client: TestClient, creator: User, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"title": "Task", "reward_points": 5}
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload, headers=auth(creator))
    return response.json()


def create_assigned_task(
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


def execution_for(
    client: TestClient, viewer: User, task_id: str, user_id: str
) -> dict[str, object]:
    executions = client.get("/api/task-executions", headers=auth(viewer)).json()
    return next(e for e in executions if e["task_id"] == task_id and e["user_id"] == user_id)


# =========================================================================================
# Task creation: POST /api/tasks
# =========================================================================================


def test_adult_creates_an_unassigned_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks",
        json={"title": "Clean room", "description": "Tidy up", "reward_points": 10},
        headers=auth(adult),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Clean room"
    assert body["description"] == "Tidy up"
    assert body["reward_points"] == 10
    assert body["is_active"] is True
    assert body["created_by"] == str(adult.id)
    assert "assigned_to" not in body
    assert "status" not in body


def test_adult_creates_a_task_directly_assigned_to_a_child(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    task = create_assigned_task(client, adult, child, title="Clean room")

    assert task["title"] == "Clean room"
    # The one self-claim slot is filled by this direct assignment, so it
    # must not also be open for another Child to self-claim (Issue #19).
    assert task["is_active"] is False
    execution = execution_for(client, adult, task["id"], str(child.id))
    assert execution["status"] == "ASSIGNED"
    assert execution["reward_points"] == 5


def test_adult_creates_a_task_directly_assigned_to_another_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")

    task = create_assigned_task(client, adult_a, adult_b)

    execution = execution_for(client, adult_a, task["id"], str(adult_b.id))
    assert execution["status"] == "ASSIGNED"


def test_adult_creates_a_task_directly_assigned_to_self(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    task = create_assigned_task(client, adult, adult)

    execution = execution_for(client, adult, task["id"], str(adult.id))
    assert execution["status"] == "ASSIGNED"


def test_directly_assigned_task_cannot_be_self_claimed_by_another_child(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = create_assigned_task(client, adult, child)

    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(other_child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_INACTIVE"


def test_child_cannot_create_task(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(
        "/api/tasks", json={"title": "Task", "reward_points": 5}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


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


def test_create_task_missing_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post("/api/tasks", json={"reward_points": 5}, headers=auth(adult))

    assert response.status_code == 422


def test_create_task_blank_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks", json={"title": "   ", "reward_points": 5}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_missing_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post("/api/tasks", json={"title": "Task"}, headers=auth(adult))

    assert response.status_code == 422


def test_create_task_zero_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks", json={"title": "Task", "reward_points": 0}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_create_task_negative_reward(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(
        "/api/tasks", json={"title": "Task", "reward_points": -1}, headers=auth(adult)
    )

    assert response.status_code == 422


def test_new_task_is_active_by_default(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    task = create_task(client, adult)

    assert task["is_active"] is True


# =========================================================================================
# Task visibility: GET /api/tasks, GET /api/tasks/{id}
# =========================================================================================


def test_creator_sees_their_own_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.get("/api/tasks", headers=auth(adult))

    assert task["id"] in [t["id"] for t in response.json()]


def test_adult_does_not_see_another_adults_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a)

    response = client.get("/api/tasks", headers=auth(adult_b))

    assert task["id"] not in [t["id"] for t in response.json()]


def test_child_sees_active_task_as_available(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)

    response = client.get("/api/tasks", headers=auth(child))

    assert task["id"] in [t["id"] for t in response.json()]


def test_child_does_not_see_inactive_task_they_have_no_execution_for(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.patch(f"/api/tasks/{task['id']}", json={"is_active": False}, headers=auth(adult))

    response = client.get("/api/tasks", headers=auth(child))

    assert task["id"] not in [t["id"] for t in response.json()]


def test_assignee_sees_task_via_their_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_assigned_task(client, adult, child)

    response = client.get("/api/tasks", headers=auth(child))

    assert task["id"] in [t["id"] for t in response.json()]


def test_child_still_sees_task_via_execution_after_it_is_deactivated(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_assigned_task(client, adult, child)
    client.patch(f"/api/tasks/{task['id']}", json={"is_active": False}, headers=auth(adult))

    response = client.get("/api/tasks", headers=auth(child))

    assert task["id"] in [t["id"] for t in response.json()]


def test_child_does_not_see_another_childs_execution_task_once_inactive(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = create_assigned_task(client, adult, child_a)
    client.patch(f"/api/tasks/{task['id']}", json={"is_active": False}, headers=auth(adult))

    response = client.get("/api/tasks", headers=auth(child_b))

    assert task["id"] not in [t["id"] for t in response.json()]


def test_self_assigned_task_is_not_duplicated_in_list(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_assigned_task(client, adult, adult)

    response = client.get("/api/tasks", headers=auth(adult))

    matches = [t for t in response.json() if t["id"] == task["id"]]
    assert len(matches) == 1


def test_creator_can_retrieve_their_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.get(f"/api/tasks/{task['id']}", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["id"] == task["id"]


def test_unrelated_adult_cannot_retrieve_the_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult)

    response = client.get(f"/api/tasks/{task['id']}", headers=auth(other_adult))

    # Existence is not leaked to a user with no relationship to the task.
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


# =========================================================================================
# Task editing: PATCH /api/tasks/{id}
# =========================================================================================


def test_creator_can_edit_title(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult, title="Old title")

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "New title"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["title"] == "New title"


def test_creator_can_edit_description(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"description": "New description"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["description"] == "New description"


def test_creator_can_edit_reward_points(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult, reward_points=5)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"reward_points": 25}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["reward_points"] == 25


def test_creator_can_deactivate_and_reactivate_a_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    deactivated = client.patch(
        f"/api/tasks/{task['id']}", json={"is_active": False}, headers=auth(adult)
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    reactivated = client.patch(
        f"/api/tasks/{task['id']}", json={"is_active": True}, headers=auth(adult)
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


def test_edit_updates_updated_at(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)
    original_updated_at = task["updated_at"]

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Updated"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["updated_at"] != original_updated_at


def test_non_creator_cannot_edit_the_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Hijacked"}, headers=auth(other_adult)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_assignee_who_is_not_the_creator_cannot_edit_the_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_assigned_task(client, adult, child)

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Hijacked"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_child_is_rejected_by_role_before_any_task_lookup(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """PATCH /api/tasks/{id} is Adult-only by role, not merely "not the
    creator": a Child must be rejected even for a Task id that doesn't
    exist, proving the role check runs before the endpoint ever looks the
    Task up (as opposed to happening to also reject Children only because
    they can never be a creator).
    """
    child = make_user(CHILD)

    response = client.patch(
        f"/api/tasks/{uuid.uuid4()}", json={"title": "Hijacked"}, headers=auth(child)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_edit_has_no_lifecycle_gate_even_with_an_in_progress_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Unlike the old single-Task model, Task itself has no lifecycle status
    any more, so editing a definition is never blocked by what state one of
    its (possibly many) executions happens to be in.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_assigned_task(client, adult, child)
    execution = execution_for(client, adult, task["id"], str(child.id))
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    response = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "Still editable"}, headers=auth(adult)
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Still editable"


def test_reward_points_change_does_not_affect_an_existing_executions_snapshot(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_assigned_task(client, adult, child, reward_points=10)
    execution = execution_for(client, adult, task["id"], str(child.id))

    client.patch(f"/api/tasks/{task['id']}", json={"reward_points": 999}, headers=auth(adult))

    unchanged = client.get(f"/api/task-executions/{execution['id']}", headers=auth(adult)).json()
    assert unchanged["reward_points"] == 10


def test_reward_points_change_applies_to_a_new_execution_created_afterwards(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, reward_points=10)

    client.patch(f"/api/tasks/{task['id']}", json={"reward_points": 40}, headers=auth(adult))
    claimed = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert claimed.status_code == 201
    assert claimed.json()["reward_points"] == 40


# =========================================================================================
# Claiming: POST /api/tasks/{id}/claim
# =========================================================================================


def test_child_can_claim_an_active_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, reward_points=20)

    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"] == task["id"]
    assert body["user_id"] == str(child.id)
    assert body["status"] == "ASSIGNED"
    assert body["reward_points"] == 20


def test_adult_cannot_claim_a_task(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    task = create_task(client, adult)

    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(other_adult))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_claim_nonexistent_task_returns_404(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    child = make_user(CHILD)

    response = client.post(f"/api/tasks/{uuid.uuid4()}/claim", headers=auth(child))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_claim_an_inactive_task_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.patch(f"/api/tasks/{task['id']}", json={"is_active": False}, headers=auth(adult))

    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_INACTIVE"


def test_claiming_flips_the_task_to_inactive(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)

    client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    refreshed = client.get(f"/api/tasks/{task['id']}", headers=auth(adult)).json()
    assert refreshed["is_active"] is False


def test_second_claim_attempt_on_an_already_claimed_task_is_rejected_as_inactive(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    """Once claimed, the Task's single self-claim slot is closed -- a second
    attempt (by the same Child or a different one) is rejected because the
    Task is now inactive, not because of the (now-relaxed) per-user
    uniqueness rule.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_INACTIVE"
    count = db_session.scalar(
        select(func.count())
        .select_from(TaskExecution)
        .where(TaskExecution.task_id == uuid.UUID(task["id"]), TaskExecution.user_id == child.id)
    )
    assert count == 1


def test_two_different_children_can_claim_the_same_task_over_time(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """The single-slot model: Child A claims (slot closes), Child B's
    attempt is rejected while the slot is closed, the creator reactivates,
    and only then can Child B claim too -- leaving two independent
    executions with independent lifecycles.
    """
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = create_task(client, adult)

    response_a = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child_a))
    assert response_a.status_code == 201

    blocked = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child_b))
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_INACTIVE"

    reactivated = client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))
    assert reactivated.json()["is_active"] is True

    response_b = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child_b))

    assert response_b.status_code == 201
    assert response_a.json()["id"] != response_b.json()["id"]
    assert response_a.json()["status"] == "ASSIGNED"
    assert response_b.json()["status"] == "ASSIGNED"

    # Reactivating and Child B claiming never touched Child A's execution.
    execution_a = client.get(
        f"/api/task-executions/{response_a.json()['id']}", headers=auth(adult)
    ).json()
    assert execution_a["status"] == "ASSIGNED"
    assert execution_a["user_id"] == str(child_a.id)


def test_same_child_can_claim_the_same_task_again_after_reactivation(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """A Task is reusable over time: once a Child's execution goes terminal
    and the creator reactivates the Task, that same Child may claim it
    again, producing a second, independent execution and (once completed) a
    second, independent PointTransaction.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, reward_points=15)

    first = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child)).json()
    client.post(f"/api/task-executions/{first['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{first['id']}/ready", headers=auth(child))
    client.post(f"/api/task-executions/{first['id']}/confirm", headers=auth(adult))

    client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))
    second = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert second.status_code == 201
    assert second.json()["id"] != first["id"]
    assert second.json()["status"] == "ASSIGNED"

    first_state = client.get(f"/api/task-executions/{first['id']}", headers=auth(adult)).json()
    assert first_state["status"] == "COMPLETED"


def test_child_cannot_reclaim_while_their_own_execution_is_still_open(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    """Reactivating a Task never touches an existing execution (Issue #19),
    so it's possible for a Child to still have a non-terminal execution of
    a Task the creator has reopened. That Child claiming again must still
    be rejected -- now via the "at most one open execution per (task,
    user)" constraint rather than the Task's is_active flag, since the flag
    alone would otherwise allow it.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    execution = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child)).json()
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))
    response = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_ALREADY_CLAIMED"


def test_unauthenticated_cannot_claim(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.post(f"/api/tasks/{task['id']}/claim")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# =========================================================================================
# Activation: POST /api/tasks/{id}/activate
# =========================================================================================


def test_creator_can_activate_a_deactivated_task(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))  # closes the slot

    response = client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_activating_an_already_active_task_is_idempotent(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_non_creator_adult_cannot_activate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/activate", headers=auth(other_adult))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    unchanged = client.get(f"/api/tasks/{task['id']}", headers=auth(adult)).json()
    assert unchanged["is_active"] is False


def test_child_cannot_activate(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/activate", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_activate_nonexistent_task_returns_404(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(f"/api/tasks/{uuid.uuid4()}/activate", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_activation_does_not_create_an_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))

    executions = client.get("/api/task-executions", headers=auth(adult)).json()
    assert executions == []


def test_activation_does_not_modify_an_existing_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult)
    execution = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child)).json()
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    client.post(f"/api/tasks/{task['id']}/activate", headers=auth(adult))

    unchanged = client.get(f"/api/task-executions/{execution['id']}", headers=auth(adult)).json()
    assert unchanged["status"] == "IN_PROGRESS"
    assert unchanged["id"] == execution["id"]


def test_unauthenticated_cannot_activate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult)

    response = client.post(f"/api/tasks/{task['id']}/activate")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# =========================================================================================
# Concurrency
# =========================================================================================


def real_session_headers(session: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Like conftest.auth(), but against an explicitly supplied, real,
    independently-committing session -- for the concurrency test below,
    which intentionally bypasses the shared savepoint-isolated db_session
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


def test_concurrent_claims_by_two_different_children_succeed_exactly_once() -> None:
    """Issue #19's single-slot rule: `is_active` represents exactly one
    self-claim slot, closed atomically by whichever claim wins the Task
    row's lock first. Two Children racing to claim the same active Task
    must yield exactly one success and one TASK_INACTIVE conflict (not
    TASK_ALREADY_CLAIMED -- these are two different Children, so the old
    per-user uniqueness rule was never in play), exactly one TaskExecution,
    and a final `is_active = False`. This is deterministic (not a matter of
    thread-scheduling luck) because Postgres's row lock, taken by every
    claim via `_get_task_for_update`, totally orders any two transactions
    that contend for it: the loser always re-reads the winner's committed
    result before deciding.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child_a = User(name="Concurrent Child A", role=CHILD)
    child_b = User(name="Concurrent Child B", role=CHILD)
    setup_session.add_all([adult, child_a, child_b])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child_a)
    setup_session.refresh(child_b)

    task = Task(title="Claim race", reward_points=10, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    headers_a = real_session_headers(setup_session, child_a.id)
    headers_b = real_session_headers(setup_session, child_b.id)

    try:
        results: list[tuple[int, dict[str, object]]] = []
        barrier = threading.Barrier(2)

        def attempt_claim(headers: dict[str, str]) -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(f"/api/tasks/{task.id}/claim", headers=headers)
            results.append((response.status_code, response.json()))

        threads = [
            threading.Thread(target=attempt_claim, args=(headers_a,)),
            threading.Thread(target=attempt_claim, args=(headers_b,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        statuses = sorted(status for status, _ in results)
        assert statuses == [201, 409]
        conflict_body = next(body for status, body in results if status == 409)
        assert conflict_body["error"]["code"] == "TASK_INACTIVE"

        setup_session.expire_all()
        execution_count = setup_session.scalar(
            select(func.count()).select_from(TaskExecution).where(TaskExecution.task_id == task.id)
        )
        assert execution_count == 1

        refreshed_task = setup_session.get(Task, task.id)
        assert refreshed_task is not None
        assert refreshed_task.is_active is False
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=child_a.id).delete()
        setup_session.query(UserSession).filter_by(user_id=child_b.id).delete()
        setup_session.query(TaskExecution).filter_by(task_id=task.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child_a.id).delete()
        setup_session.query(User).filter_by(id=child_b.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


def test_concurrent_claim_cannot_race_ahead_of_an_in_flight_deactivation() -> None:
    """If a Task's deactivation has already committed before a claim obtains
    its authoritative Task state, that claim must not create an execution.

    A `threading.Barrier`-released race (like the double-claim test above)
    isn't a reliable way to exercise this specific invariant: the window
    between claim's `is_active` read and its INSERT is a handful of Python
    statements wide, so two independently-scheduled threads would only hit
    it by luck, making the test flaky in both the buggy and fixed states.
    Instead, this deterministically forces the interleaving that would
    expose a missing row lock: a second, real session takes and holds
    `SELECT ... FOR UPDATE` on the Task row first (standing in for
    `PATCH .../deactivate` reaching that same lock first), a claim request
    is started in a background thread while that lock is held, and only
    then is the Task deactivated and the lock released. If claim correctly
    takes the same row lock, it blocks until this releases, re-reads the
    now-inactive Task, and is rejected; without the lock, claim would race
    ahead on the stale is_active=True snapshot and wrongly succeed.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Claim vs deactivate race", reward_points=10, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    auth_headers = real_session_headers(setup_session, child.id)

    lock_session = SessionLocal()
    try:
        locked_task = lock_session.execute(
            select(Task).where(Task.id == task.id).with_for_update()
        ).scalar_one()

        claim_result: dict[str, int] = {}

        def attempt_claim() -> None:
            with TestClient(app) as thread_client:
                response = thread_client.post(f"/api/tasks/{task.id}/claim", headers=auth_headers)
            claim_result["status"] = response.status_code

        claim_thread = threading.Thread(target=attempt_claim)
        claim_thread.start()
        # Give the claim request time to reach and block on the row lock
        # held above before it's released below. If it somehow doesn't
        # block in time, the assertions below would only produce a false
        # pass (claim just happens to run after the deactivation anyway),
        # never mask a real bug.
        time.sleep(0.3)

        locked_task.is_active = False
        lock_session.commit()

        claim_thread.join(timeout=5)

        assert claim_result.get("status") == 409

        setup_session.expire_all()
        execution_count = setup_session.scalar(
            select(func.count())
            .select_from(TaskExecution)
            .where(TaskExecution.task_id == task.id, TaskExecution.user_id == child.id)
        )
        assert execution_count == 0

        refreshed_task = setup_session.get(Task, task.id)
        assert refreshed_task is not None
        assert refreshed_task.is_active is False
    finally:
        lock_session.close()
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=child.id).delete()
        setup_session.query(TaskExecution).filter_by(task_id=task.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()
