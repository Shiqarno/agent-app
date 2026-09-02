import uuid
from collections.abc import Callable

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PointTransaction, PointTransactionReason, User, UserRole

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


def transactions_for(db_session: Session, task_id: str) -> list[PointTransaction]:
    stmt = select(PointTransaction).where(PointTransaction.task_id == uuid.UUID(task_id))
    return list(db_session.scalars(stmt))


def complete_lifecycle(
    client: TestClient, adult: User, assignee: User, task: dict[str, object]
) -> None:
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(assignee))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(assignee))
    client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))


# --- Basic awarding -------------------------------------------------------------------


def test_confirming_a_task_creates_exactly_one_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=50)

    complete_lifecycle(client, adult, child, task)

    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1
    txn = txns[0]
    assert txn.amount == 50
    assert txn.reason == PointTransactionReason.TASK_COMPLETED
    assert txn.user_id == child.id
    assert txn.task_id == uuid.UUID(str(task["id"]))


# --- Different assignee roles ----------------------------------------------------------


def test_adult_to_child_awards_the_child(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=15)

    complete_lifecycle(client, adult, child, task)

    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1
    assert txns[0].user_id == child.id


def test_adult_to_adult_awards_the_assignee(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    task = create_task(client, adult_a, adult_b, reward_points=15)

    complete_lifecycle(client, adult_a, adult_b, task)

    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1
    assert txns[0].user_id == adult_b.id


def test_adult_to_self_awards_the_same_adult(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    task = create_task(client, adult, adult, reward_points=15)

    complete_lifecycle(client, adult, adult, task)

    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1
    assert txns[0].user_id == adult.id


# --- Lifecycle restrictions -------------------------------------------------------------


def test_no_transaction_after_task_creation(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)

    assert transactions_for(db_session, str(task["id"])) == []


def test_no_transaction_after_task_start(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))

    assert transactions_for(db_session, str(task["id"])) == []


def test_no_transaction_after_task_marked_ready(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    assert transactions_for(db_session, str(task["id"])) == []


# --- Failed confirmation -----------------------------------------------------------------


def test_failed_confirmation_by_non_creator_creates_no_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(other_adult))

    assert response.status_code == 403
    task_state = client.get("/api/tasks", headers=auth(adult)).json()[0]
    assert task_state["status"] == "AWAITING_CONFIRMATION"
    assert transactions_for(db_session, str(task["id"])) == []


def test_confirming_too_early_creates_no_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    # not marked ready yet

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert response.status_code == 409
    assert transactions_for(db_session, str(task["id"])) == []


# --- Exactly once -----------------------------------------------------------------------


def test_repeated_confirmation_does_not_duplicate_the_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=30)
    complete_lifecycle(client, adult, child, task)

    second_attempt = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert second_attempt.status_code == 409
    assert second_attempt.json()["error"]["code"] == "INVALID_TRANSITION"
    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1


def test_database_rejects_a_second_task_completed_transaction_directly(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=30)
    complete_lifecycle(client, adult, child, task)

    duplicate = PointTransaction(
        user_id=child.id,
        task_id=uuid.UUID(str(task["id"])),
        amount=30,
        reason=PointTransactionReason.TASK_COMPLETED,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- Atomicity --------------------------------------------------------------------------


def test_confirmation_rolls_back_task_status_when_transaction_insert_conflicts(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = create_task(client, adult, child, reward_points=30)
    client.post(f"/api/tasks/{task['id']}/start", headers=auth(child))
    client.post(f"/api/tasks/{task['id']}/ready", headers=auth(child))

    # Simulate a conflicting transaction already existing for this task (e.g. a race),
    # bypassing the API entirely, directly at the database level.
    db_session.add(
        PointTransaction(
            user_id=child.id,
            task_id=uuid.UUID(str(task["id"])),
            amount=999,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    db_session.commit()

    response = client.post(f"/api/tasks/{task['id']}/confirm", headers=auth(adult))

    assert response.status_code == 409

    # The task's status change must have rolled back together with the failed
    # transaction insert -- it must NOT be COMPLETED despite the conflict occurring
    # only on the PointTransaction insert.
    task_state = client.get("/api/tasks", headers=auth(adult)).json()[0]
    assert task_state["status"] == "AWAITING_CONFIRMATION"

    txns = transactions_for(db_session, str(task["id"]))
    assert len(txns) == 1
    assert txns[0].amount == 999
