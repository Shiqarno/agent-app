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
from app.models import (
    PointTransaction,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
    UserSession,
    utcnow,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def create_execution(
    client: TestClient, creator: User, assignee: User, **overrides: object
) -> dict[str, object]:
    """Creates a Task directly assigned to `assignee` and returns the
    resulting TaskExecution.
    """
    payload: dict[str, object] = {
        "title": "Task",
        "assigned_to": str(assignee.id),
        "reward_points": 5,
    }
    payload.update(overrides)
    task = client.post("/api/tasks", json=payload, headers=auth(creator)).json()
    executions = client.get("/api/task-executions", headers=auth(creator)).json()
    return next(e for e in executions if e["task_id"] == task["id"])


# =========================================================================================
# AC: Adult assigns to Child, another Adult, or themselves; assignee can start/mark ready
# =========================================================================================


def test_assigned_user_can_start_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    execution = create_execution(client, adult_a, adult_b)

    response = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult_b))

    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"


def test_assigned_user_can_mark_execution_ready(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    execution = create_execution(client, adult_a, adult_b)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult_b))

    response = client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(adult_b))

    assert response.status_code == 200
    assert response.json()["status"] == "AWAITING_CONFIRMATION"


def test_creator_confirms_execution_assigned_to_another_adult(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    execution = create_execution(client, adult_a, adult_b)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult_b))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(adult_b))

    response = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult_a))

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"


def test_self_assigned_execution_can_complete_full_lifecycle(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    execution = create_execution(client, adult, adult)

    start = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult))
    assert start.json()["status"] == "IN_PROGRESS"

    ready = client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(adult))
    assert ready.json()["status"] == "AWAITING_CONFIRMATION"

    confirm = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "COMPLETED"


def test_child_assignment_lifecycle_works(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    ready = client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))
    assert ready.json()["status"] == "AWAITING_CONFIRMATION"

    confirm = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "COMPLETED"


# =========================================================================================
# Authorization: non-assignee cannot start/mark ready
# =========================================================================================


def test_non_assignee_adult_cannot_start_another_adults_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    adult_c = make_user(ADULT, "Adult C")
    execution = create_execution(client, adult_a, adult_b)

    response = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult_c))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get(f"/api/task-executions/{execution['id']}", headers=auth(adult_b)).json()
    assert unchanged["status"] == "ASSIGNED"


def test_non_assignee_child_cannot_start_another_childs_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    execution = create_execution(client, adult, child_a)

    response = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_non_assignee_cannot_mark_execution_ready(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    execution = create_execution(client, adult, child_a)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child_a))

    response = client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- non-creator cannot confirm, even the assignee -------------------------------------


def test_assignee_cannot_confirm_their_own_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    execution = create_execution(client, adult_a, adult_b)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(adult_b))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(adult_b))

    response = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult_b))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    unchanged = client.get(f"/api/task-executions/{execution['id']}", headers=auth(adult_a)).json()
    assert unchanged["status"] == "AWAITING_CONFIRMATION"


def test_child_cannot_confirm_completion(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))

    response = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# =========================================================================================
# Visibility: GET /api/task-executions, GET /api/task-executions/{id}
# =========================================================================================


def test_execution_visible_to_both_creator_and_assignee(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    adult_c = make_user(ADULT, "Adult C")
    execution = create_execution(client, adult_a, adult_b)

    creator_view = client.get("/api/task-executions", headers=auth(adult_a)).json()
    assert execution["id"] in [e["id"] for e in creator_view]

    assignee_view = client.get("/api/task-executions", headers=auth(adult_b)).json()
    assert execution["id"] in [e["id"] for e in assignee_view]

    unrelated_view = client.get("/api/task-executions", headers=auth(adult_c)).json()
    assert execution["id"] not in [e["id"] for e in unrelated_view]


def test_child_cannot_see_another_childs_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    create_execution(client, adult, child_a)

    response = client.get("/api/task-executions", headers=auth(child_b))

    assert response.status_code == 200
    assert response.json() == []


def test_unrelated_user_cannot_retrieve_the_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    execution = create_execution(client, adult, child)

    response = client.get(f"/api/task-executions/{execution['id']}", headers=auth(other_adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_EXECUTION_NOT_FOUND"


def test_unauthenticated_cannot_retrieve_an_execution(client: TestClient) -> None:
    response = client.get(f"/api/task-executions/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_execution_returns_404(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.get(f"/api/task-executions/{uuid.uuid4()}", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_EXECUTION_NOT_FOUND"


def test_execution_not_found_for_start(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.post(f"/api/task-executions/{uuid.uuid4()}/start", headers=auth(child))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_EXECUTION_NOT_FOUND"


def test_execution_not_found_for_confirm(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.post(f"/api/task-executions/{uuid.uuid4()}/confirm", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_EXECUTION_NOT_FOUND"


# =========================================================================================
# Invalid state transitions
# =========================================================================================


def test_cannot_mark_ready_before_starting(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_confirm_before_ready(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    response = client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_start_execution_twice(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    response = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cannot_transition_a_completed_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))

    response = client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


# =========================================================================================
# Reassignment: POST /api/task-executions/{id}/reassign
# =========================================================================================


def test_creator_can_reassign_an_assigned_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(other_child.id)
    assert response.json()["status"] == "ASSIGNED"


def test_reassign_target_user_must_exist(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(uuid.uuid4())},
        headers=auth(adult),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_FOUND"


def test_reassign_to_a_user_who_already_has_an_execution_is_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    execution = create_execution(client, adult, child)
    # other_child claims the same task independently, so they already have
    # an execution for it -- reassigning `execution` onto them would violate
    # the UNIQUE(task_id, user_id) constraint.
    client.post(f"/api/tasks/{execution['task_id']}/claim", headers=auth(other_child))

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 409


def test_reassignment_updates_updated_at(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.json()["updated_at"] != execution["updated_at"]


def test_assignee_cannot_reassign(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(child),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_other_users_cannot_reassign(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
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
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
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
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(other_child.id)},
        headers=auth(adult),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_reassignment_to_self_works(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/reassign",
        json={"assigned_to": str(adult.id)},
        headers=auth(adult),
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(adult.id)


# =========================================================================================
# Cancellation: POST /api/task-executions/{id}/cancel
# =========================================================================================


def test_creator_can_cancel_an_assigned_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_creator_can_cancel_an_in_progress_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_creator_can_cancel_an_awaiting_confirmation_execution(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancellation_updates_updated_at(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.json()["updated_at"] != execution["updated_at"]


def test_assignee_cannot_cancel(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(child))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_other_users_cannot_cancel(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_adult = make_user(ADULT, "Other Adult")
    execution = create_execution(client, adult, child)

    response = client.post(
        f"/api/task-executions/{execution['id']}/cancel", headers=auth(other_adult)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_completed_execution_cannot_be_cancelled(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cancelled_execution_cannot_be_cancelled_again(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    response = client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"


def test_cancellation_creates_no_point_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))

    client.post(f"/api/task-executions/{execution['id']}/cancel", headers=auth(adult))

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.task_execution_id == uuid.UUID(execution["id"]))
    )
    assert count == 0


def test_confirm_creates_exactly_one_task_completion_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    execution = create_execution(client, adult, child, reward_points=15)
    client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
    client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))

    client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))

    transactions = list(
        db_session.scalars(
            select(PointTransaction).where(
                PointTransaction.task_execution_id == uuid.UUID(execution["id"])
            )
        )
    )
    assert len(transactions) == 1
    assert transactions[0].amount == 15
    assert transactions[0].reason.value == "TASK_COMPLETED"


def test_two_children_completing_the_same_task_produce_two_independent_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    task = client.post(
        "/api/tasks", json={"title": "Shared task", "reward_points": 12}, headers=auth(adult)
    ).json()
    execution_a = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child_a)).json()
    execution_b = client.post(f"/api/tasks/{task['id']}/claim", headers=auth(child_b)).json()

    for execution, child in ((execution_a, child_a), (execution_b, child_b)):
        client.post(f"/api/task-executions/{execution['id']}/start", headers=auth(child))
        client.post(f"/api/task-executions/{execution['id']}/ready", headers=auth(child))
        client.post(f"/api/task-executions/{execution['id']}/confirm", headers=auth(adult))

    transactions = list(
        db_session.scalars(
            select(PointTransaction).where(
                PointTransaction.task_execution_id.in_(
                    [uuid.UUID(execution_a["id"]), uuid.UUID(execution_b["id"])]
                )
            )
        )
    )
    assert len(transactions) == 2
    assert {t.task_execution_id for t in transactions} == {
        uuid.UUID(execution_a["id"]),
        uuid.UUID(execution_b["id"]),
    }


# =========================================================================================
# Concurrency
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


def _make_race_pair(setup_session: Session) -> tuple[User, User, Task]:
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Race me", reward_points=25, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)
    return adult, child, task


def test_concurrent_confirm_requests_succeed_exactly_once() -> None:
    """Two simultaneous confirm requests on the same execution must not both
    succeed -- the row lock serializes them, so the second sees the
    already-COMPLETED status and is correctly rejected, leaving exactly one
    TASK_COMPLETED transaction.
    """
    setup_session = SessionLocal()
    adult, child, task = _make_race_pair(setup_session)
    execution = TaskExecution(
        task_id=task.id,
        user_id=child.id,
        status=TaskExecutionStatus.AWAITING_CONFIRMATION,
        reward_points=25,
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def attempt_confirm() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/task-executions/{execution.id}/confirm", headers=auth_headers
                )
            results.append(response.status_code)

        threads = [threading.Thread(target=attempt_confirm) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [200, 409]

        setup_session.expire_all()
        final_execution = setup_session.get(TaskExecution, execution.id)
        assert final_execution is not None
        assert final_execution.status == TaskExecutionStatus.COMPLETED
        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_execution_id == execution.id)
        )
        assert transaction_count == 1
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(PointTransaction).filter_by(task_execution_id=execution.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


def test_concurrent_confirm_and_cancel_cannot_both_succeed() -> None:
    """An execution in AWAITING_CONFIRMATION racing between the creator's
    confirm and the creator's cancel must not end up COMPLETED-with-no-
    transaction nor CANCELLED-with-a-stray-TASK_COMPLETED-transaction.
    Exactly one request must win; the loser must see a real rejection.
    """
    setup_session = SessionLocal()
    adult, child, task = _make_race_pair(setup_session)
    execution = TaskExecution(
        task_id=task.id,
        user_id=child.id,
        status=TaskExecutionStatus.AWAITING_CONFIRMATION,
        reward_points=25,
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: dict[str, int] = {}
        barrier = threading.Barrier(2)

        def attempt(action: str) -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/task-executions/{execution.id}/{action}", headers=auth_headers
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
        final_execution = setup_session.get(TaskExecution, execution.id)
        assert final_execution is not None
        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_execution_id == execution.id)
        )

        if results["confirm"] == 200:
            assert final_execution.status == TaskExecutionStatus.COMPLETED
            assert transaction_count == 1
        else:
            assert final_execution.status == TaskExecutionStatus.CANCELLED
            assert transaction_count == 0
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(PointTransaction).filter_by(task_execution_id=execution.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


def test_concurrent_cancel_requests_leave_exactly_one_terminal_transition() -> None:
    """Two simultaneous cancel requests on the same execution must not both
    report success -- the row lock serializes them, so the second sees the
    already-CANCELLED status and is correctly rejected.
    """
    setup_session = SessionLocal()
    adult, child, task = _make_race_pair(setup_session)
    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.ASSIGNED, reward_points=10
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def attempt_cancel() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/task-executions/{execution.id}/cancel", headers=auth_headers
                )
            results.append(response.status_code)

        threads = [threading.Thread(target=attempt_cancel) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [200, 409]

        setup_session.expire_all()
        final_execution = setup_session.get(TaskExecution, execution.id)
        assert final_execution is not None
        assert final_execution.status == TaskExecutionStatus.CANCELLED
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


def test_concurrent_reassign_and_start_never_let_the_obsolete_executor_start() -> None:
    """Reassign-vs-start race: the row lock serializes a concurrent reassign
    (by the creator, to a new user) against the original assignee's start.
    Whichever commits first wins; the other must see a rejection -- the
    original assignee must never succeed at starting after having been
    reassigned away, and a successful start must never leave the execution
    reassigned out from under it.
    """
    setup_session = SessionLocal()
    adult, child, task = _make_race_pair(setup_session)
    other_child = User(name="Other Concurrent Child", role=CHILD)
    setup_session.add(other_child)
    setup_session.commit()
    setup_session.refresh(other_child)

    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.ASSIGNED, reward_points=25
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    adult_headers = real_session_headers(setup_session, adult.id)
    child_headers = real_session_headers(setup_session, child.id)

    try:
        results: dict[str, int] = {}
        barrier = threading.Barrier(2)

        def attempt_reassign() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/task-executions/{execution.id}/reassign",
                    json={"assigned_to": str(other_child.id)},
                    headers=adult_headers,
                )
            results["reassign"] = response.status_code

        def attempt_start() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/task-executions/{execution.id}/start", headers=child_headers
                )
            results["start"] = response.status_code

        threads = [
            threading.Thread(target=attempt_reassign),
            threading.Thread(target=attempt_start),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        setup_session.expire_all()
        final_execution = setup_session.get(TaskExecution, execution.id)
        assert final_execution is not None

        if results["start"] == 200:
            # start committed first: execution is IN_PROGRESS, still owned
            # by the original child, and the reassign that ran afterwards
            # must have seen the now-non-ASSIGNED status and been rejected.
            assert final_execution.status == TaskExecutionStatus.IN_PROGRESS
            assert final_execution.user_id == child.id
            assert results["reassign"] == 409
        else:
            # reassign committed first: execution now belongs to
            # other_child, and the original child's start must have been
            # rejected as forbidden (they're no longer the assignee).
            assert results["start"] == 403
            assert results["reassign"] == 200
            assert final_execution.status == TaskExecutionStatus.ASSIGNED
            assert final_execution.user_id == other_child.id
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(UserSession).filter_by(user_id=child.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter_by(id=other_child.id).delete()
        setup_session.query(User).filter_by(id=child.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()
