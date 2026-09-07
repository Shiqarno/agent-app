import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import PointTransaction, Task, TaskExecution, TaskExecutionStatus, User, UserRole
from app.task_operations import (
    NotAChildError,
    TaskExecutionNotActionableError,
    TaskNotClaimableError,
    claim_task,
    get_available_tasks,
    get_my_tasks,
    mark_execution_ready,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_task(
    db_session: Session,
    creator: User,
    *,
    title: str = "Clean room",
    reward_points: int = 20,
    is_active: bool = True,
) -> Task:
    task = Task(
        title=title, reward_points=reward_points, is_active=is_active, created_by=creator.id
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def _make_execution(
    db_session: Session,
    task: Task,
    user: User,
    status: TaskExecutionStatus,
    *,
    reward_points: int | None = None,
) -> TaskExecution:
    execution = TaskExecution(
        task_id=task.id,
        user_id=user.id,
        status=status,
        reward_points=reward_points if reward_points is not None else task.reward_points,
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


# =========================================================================================
# get_available_tasks
# =========================================================================================


def test_active_available_task_appears(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)

    tasks = get_available_tasks(db_session, child)

    assert [t.id for t in tasks] == [task.id]


def test_inactive_task_does_not_appear(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task(db_session, adult, is_active=False)

    assert get_available_tasks(db_session, child) == []


def test_task_with_an_open_execution_for_this_user_is_not_claimable(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    # is_active stays True (e.g. an Adult reactivated it) even though this
    # Child already has an open execution -- must still be excluded.
    _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    assert get_available_tasks(db_session, child) == []


def test_completed_historical_execution_does_not_suppress_availability(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, TaskExecutionStatus.COMPLETED)

    tasks = get_available_tasks(db_session, child)

    assert [t.id for t in tasks] == [task.id]


def test_cancelled_historical_execution_does_not_suppress_availability(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, TaskExecutionStatus.CANCELLED)

    tasks = get_available_tasks(db_session, child)

    assert [t.id for t in tasks] == [task.id]


def test_available_tasks_reward_points_come_from_the_current_task_definition(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=20)
    task.reward_points = 35
    db_session.commit()

    tasks = get_available_tasks(db_session, child)

    assert tasks[0].reward_points == 35


def test_get_available_tasks_rejects_a_non_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(NotAChildError):
        get_available_tasks(db_session, adult)


# =========================================================================================
# claim_task
# =========================================================================================


def test_claim_creates_an_execution(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)

    execution, returned_task = claim_task(db_session, child, task.id)

    assert execution.task_id == task.id
    assert execution.user_id == child.id
    assert returned_task.id == task.id


def test_claim_starts_in_progress(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)

    execution, _ = claim_task(db_session, child, task.id)

    assert execution.status == TaskExecutionStatus.IN_PROGRESS


def test_claim_snapshots_the_reward(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=42)

    execution, _ = claim_task(db_session, child, task.id)

    assert execution.reward_points == 42


def test_claim_does_not_mutate_the_task_reward(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=42)

    claim_task(db_session, child, task.id)

    db_session.refresh(task)
    assert task.reward_points == 42


def test_claim_closes_the_self_claim_slot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)

    _, returned_task = claim_task(db_session, child, task.id)

    assert returned_task.is_active is False


def test_child_cannot_create_a_second_open_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    claim_task(db_session, child, task.id)

    # Simulate an Adult reactivating the Task while the Child's execution is
    # still open -- get_available_tasks would already hide it, but claim_task
    # itself must still refuse a direct attempt.
    task.is_active = True
    db_session.commit()

    with pytest.raises(TaskNotClaimableError):
        claim_task(db_session, child, task.id)


def test_claiming_a_nonexistent_task_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(TaskNotClaimableError):
        claim_task(db_session, child, uuid.uuid4())


def test_claiming_an_inactive_task_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=False)

    with pytest.raises(TaskNotClaimableError):
        claim_task(db_session, child, task.id)


def test_claiming_as_an_adult_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult)

    with pytest.raises(NotAChildError):
        claim_task(db_session, adult, task.id)


# =========================================================================================
# get_my_tasks
# =========================================================================================


def test_my_tasks_returns_only_current_users_executions(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = _make_task(db_session, adult)
    mine = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)
    _make_execution(db_session, task, other_child, TaskExecutionStatus.IN_PROGRESS)

    items = get_my_tasks(db_session, child)

    assert [execution.id for execution, _ in items] == [mine.id]


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.AWAITING_CONFIRMATION,
    ],
)
def test_my_tasks_includes_open_statuses(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, status)

    items = get_my_tasks(db_session, child)

    assert [e.id for e, _ in items] == [execution.id]


@pytest.mark.parametrize("status", [TaskExecutionStatus.COMPLETED, TaskExecutionStatus.CANCELLED])
def test_my_tasks_excludes_terminal_statuses(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, status)

    assert get_my_tasks(db_session, child) == []


def test_my_tasks_does_not_expose_another_users_executions(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, other_child, TaskExecutionStatus.IN_PROGRESS)

    assert get_my_tasks(db_session, child) == []


# =========================================================================================
# mark_execution_ready
# =========================================================================================


def test_mark_ready_transitions_in_progress_to_awaiting_confirmation(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    updated, _ = mark_execution_ready(db_session, child, execution.id)

    assert updated.status == TaskExecutionStatus.AWAITING_CONFIRMATION


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.AWAITING_CONFIRMATION,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.CANCELLED,
    ],
)
def test_mark_ready_rejects_wrong_status(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, status)

    with pytest.raises(TaskExecutionNotActionableError):
        mark_execution_ready(db_session, child, execution.id)


def test_mark_ready_rejects_another_users_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, other_child, TaskExecutionStatus.IN_PROGRESS)

    with pytest.raises(TaskExecutionNotActionableError):
        mark_execution_ready(db_session, child, execution.id)


def test_mark_ready_creates_no_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    mark_execution_ready(db_session, child, execution.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.task_execution_id == execution.id)
    )
    assert count == 0


def test_mark_ready_rejects_nonexistent_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(TaskExecutionNotActionableError):
        mark_execution_ready(db_session, child, uuid.uuid4())


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_claims_by_two_children_succeed_exactly_once() -> None:
    """Same invariant as the Web claim endpoint's own concurrency test
    (Issue #19): two Children racing to claim the same Task must yield
    exactly one success and exactly one TaskNotClaimableError, exactly one
    TaskExecution, and a final is_active=False. Real independently-
    committing sessions, matching this project's established pattern.
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

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(user_id: uuid.UUID) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                user = session.get(User, user_id)
                assert user is not None
                claim_task(session, user, task.id)
                results.append("success")
            except TaskNotClaimableError:
                results.append("conflict")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(child_a.id,)),
            threading.Thread(target=attempt, args=(child_b.id,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["conflict", "success"]

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
        setup_session.query(TaskExecution).filter_by(task_id=task.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult.id, child_a.id, child_b.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
