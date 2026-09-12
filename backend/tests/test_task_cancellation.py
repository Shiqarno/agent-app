import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    PointTransaction,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)
from app.task_operations import (
    NotAnAdultError,
    TaskExecutionNotActionableError,
    TaskExecutionNotCancellableError,
    cancel_execution,
    claim_task,
    mark_execution_ready,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_task(
    db_session: Session, creator: User, *, title: str = "Clean room", reward_points: int = 20
) -> Task:
    task = Task(title=title, reward_points=reward_points, created_by=creator.id)
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
# cancel_execution -- happy paths
# =========================================================================================


def test_adult_can_cancel_an_assigned_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    updated, returned_task, returned_child = cancel_execution(db_session, adult, execution.id)

    assert updated.status == TaskExecutionStatus.CANCELLED
    assert returned_task.id == task.id
    assert returned_child.id == child.id


def test_adult_can_cancel_an_in_progress_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    updated, _, _ = cancel_execution(db_session, adult, execution.id)

    assert updated.status == TaskExecutionStatus.CANCELLED


def test_any_adult_can_cancel_regardless_of_task_ownership(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Mirrors the existing confirm_execution precedent (Issue #25 section
    9): there is deliberately no Adult<->Child (or Adult<->Task) ownership
    relationship, so Adult B, who did not create the Task, must still be
    able to cancel an execution of it. This is the existing authorization
    model being preserved, not a new rule.
    """
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    child = make_user(CHILD)
    task = _make_task(db_session, adult_a)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    updated, _, _ = cancel_execution(db_session, adult_b, execution.id)

    assert updated.status == TaskExecutionStatus.CANCELLED


# =========================================================================================
# cancel_execution -- authorization
# =========================================================================================


def test_child_cannot_cancel(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    with pytest.raises(NotAnAdultError):
        cancel_execution(db_session, child, execution.id)

    db_session.refresh(execution)
    assert execution.status == TaskExecutionStatus.ASSIGNED


def test_cancelling_a_missing_execution_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(TaskExecutionNotCancellableError):
        cancel_execution(db_session, adult, uuid.uuid4())


# =========================================================================================
# cancel_execution -- state boundaries
# =========================================================================================


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.AWAITING_CONFIRMATION,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.CANCELLED,
    ],
)
def test_cancelling_wrong_status_is_rejected(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, status)

    with pytest.raises(TaskExecutionNotCancellableError):
        cancel_execution(db_session, adult, execution.id)

    db_session.refresh(execution)
    assert execution.status == status


# =========================================================================================
# cancel_execution -- side effects (Task, points, history)
# =========================================================================================


def test_cancel_creates_no_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    cancel_execution(db_session, adult, execution.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.task_execution_id == execution.id)
    )
    assert count == 0


def test_cancel_preserves_the_task_definition(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, title="Clean room", reward_points=20)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    cancel_execution(db_session, adult, execution.id)

    db_session.refresh(task)
    assert task.title == "Clean room"
    assert task.reward_points == 20


@pytest.mark.parametrize("is_active", [True, False])
def test_cancel_preserves_task_is_active(
    make_user: Callable[..., User], db_session: Session, is_active: bool
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    task.is_active = is_active
    db_session.commit()
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    cancel_execution(db_session, adult, execution.id)

    db_session.refresh(task)
    assert task.is_active is is_active


def test_cancel_preserves_execution_history(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """The cancelled row is never deleted -- it remains queryable with
    status CANCELLED, exactly like a COMPLETED execution stays around.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    cancel_execution(db_session, adult, execution.id)

    persisted = db_session.get(TaskExecution, execution.id)
    assert persisted is not None
    assert persisted.status == TaskExecutionStatus.CANCELLED


def test_active_task_can_be_claimed_again_after_cancellation(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """A directly-assigned execution never touches Task.is_active (see
    assign_task), so cancelling it leaves an already-active Task claimable
    right away -- no separate reactivation step needed.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    assert task.is_active is True
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    cancel_execution(db_session, adult, execution.id)

    new_execution, _ = claim_task(db_session, child, task.id)

    assert new_execution.id != execution.id
    assert new_execution.status == TaskExecutionStatus.IN_PROGRESS


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_cancel_vs_mark_ready_produces_exactly_one_valid_outcome() -> None:
    """An Adult cancelling and a Child marking the same execution ready,
    racing on the same IN_PROGRESS execution, must yield exactly one
    winner: either CANCELLED, or AWAITING_CONFIRMATION -- never both, and
    never a CANCELLED execution that had already reached
    AWAITING_CONFIRMATION.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Cancel race", reward_points=10, created_by=adult.id, is_active=False)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id,
        user_id=child.id,
        status=TaskExecutionStatus.IN_PROGRESS,
        reward_points=10,
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt_cancel() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                acting_adult = session.get(User, adult.id)
                assert acting_adult is not None
                cancel_execution(session, acting_adult, execution.id)
                results.append("cancelled")
            except TaskExecutionNotCancellableError:
                results.append("cancel-rejected")
            finally:
                session.close()

        def attempt_mark_ready() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                acting_child = session.get(User, child.id)
                assert acting_child is not None
                mark_execution_ready(session, acting_child, execution.id)
                results.append("marked-ready")
            except TaskExecutionNotActionableError:
                results.append("mark-ready-rejected")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt_cancel),
            threading.Thread(target=attempt_mark_ready),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        winners = [r for r in results if r in ("cancelled", "marked-ready")]
        assert len(winners) == 1

        setup_session.expire_all()
        refreshed = setup_session.get(TaskExecution, execution.id)
        assert refreshed is not None

        if winners == ["cancelled"]:
            assert refreshed.status == TaskExecutionStatus.CANCELLED
        else:
            assert refreshed.status == TaskExecutionStatus.AWAITING_CONFIRMATION

        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_execution_id == execution.id)
        )
        assert transaction_count == 0
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(task_execution_id=execution.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
