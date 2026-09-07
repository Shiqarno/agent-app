import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)
from app.task_operations import (
    NotAnAdultError,
    TaskExecutionNotConfirmableError,
    confirm_execution,
    get_pending_confirmations,
    return_execution_to_work,
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
# get_pending_confirmations
# =========================================================================================


def test_returns_awaiting_confirmation(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    items = get_pending_confirmations(db_session, adult)

    assert [e.id for e, _, _ in items] == [execution.id]


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.CANCELLED,
    ],
)
def test_excludes_other_statuses(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, status)

    assert get_pending_confirmations(db_session, adult) == []


def test_returns_the_correct_task_and_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD, "Vova")
    task = _make_task(db_session, adult, title="Clean room")
    _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    [(_, returned_task, returned_child)] = get_pending_confirmations(db_session, adult)

    assert returned_task.id == task.id
    assert returned_child.id == child.id
    assert returned_child.name == "Vova"


def test_returns_the_execution_reward_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=20)
    _make_execution(
        db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION, reward_points=20
    )
    task.reward_points = 99  # changed after the execution snapshot was taken
    db_session.commit()

    [(execution, _, _)] = get_pending_confirmations(db_session, adult)

    assert execution.reward_points == 20


def test_does_not_expose_an_unrelated_user_as_the_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD, "Correct Child")
    other = make_user(CHILD, "Unrelated User")
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    [(_, _, returned_child)] = get_pending_confirmations(db_session, adult)

    assert returned_child.id != other.id
    assert returned_child.id == child.id


def test_get_pending_confirmations_rejects_a_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        get_pending_confirmations(db_session, child)


# =========================================================================================
# confirm_execution
# =========================================================================================


def test_adult_can_confirm(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    updated, returned_task, returned_child = confirm_execution(db_session, adult, execution.id)

    assert updated.status == TaskExecutionStatus.COMPLETED
    assert returned_task.id == task.id
    assert returned_child.id == child.id


def test_any_adult_can_confirm_regardless_of_task_ownership(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Issue #25 section 9: there is deliberately no Adult<->Child (or
    Adult<->Task) ownership relationship -- Adult B, who did not create the
    Task, must still be able to confirm it.
    """
    adult_a = make_user(ADULT, "Adult A")
    adult_b = make_user(ADULT, "Adult B")
    child = make_user(CHILD)
    task = _make_task(db_session, adult_a)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    updated, _, _ = confirm_execution(db_session, adult_b, execution.id)

    assert updated.status == TaskExecutionStatus.COMPLETED


def test_child_cannot_confirm(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    with pytest.raises(NotAnAdultError):
        confirm_execution(db_session, child, execution.id)


def test_confirming_a_missing_execution_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(TaskExecutionNotConfirmableError):
        confirm_execution(db_session, adult, uuid.uuid4())


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.CANCELLED,
    ],
)
def test_confirming_wrong_status_is_rejected(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, status)

    with pytest.raises(TaskExecutionNotConfirmableError):
        confirm_execution(db_session, adult, execution.id)


def test_confirm_creates_exactly_one_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    confirm_execution(db_session, adult, execution.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.task_execution_id == execution.id,
            PointTransaction.reason == PointTransactionReason.TASK_COMPLETED,
        )
    )
    assert count == 1


def test_confirm_transaction_amount_equals_execution_reward_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=20)
    execution = _make_execution(
        db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION, reward_points=20
    )
    task.reward_points = 99  # must not affect the payout
    db_session.commit()

    confirm_execution(db_session, adult, execution.id)

    transaction = db_session.scalars(
        select(PointTransaction).where(PointTransaction.task_execution_id == execution.id)
    ).one()
    assert transaction.amount == 20


def test_confirm_transaction_belongs_to_the_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    confirm_execution(db_session, adult, execution.id)

    transaction = db_session.scalars(
        select(PointTransaction).where(PointTransaction.task_execution_id == execution.id)
    ).one()
    assert transaction.user_id == child.id


# =========================================================================================
# return_execution_to_work
# =========================================================================================


def test_adult_can_return(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    updated, returned_task, returned_child = return_execution_to_work(
        db_session, adult, execution.id
    )

    assert updated.status == TaskExecutionStatus.IN_PROGRESS
    assert returned_task.id == task.id
    assert returned_child.id == child.id


def test_child_cannot_return(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    with pytest.raises(NotAnAdultError):
        return_execution_to_work(db_session, child, execution.id)


def test_returning_a_missing_execution_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(TaskExecutionNotConfirmableError):
        return_execution_to_work(db_session, adult, uuid.uuid4())


@pytest.mark.parametrize(
    "status",
    [
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.COMPLETED,
        TaskExecutionStatus.CANCELLED,
    ],
)
def test_returning_wrong_status_is_rejected(
    make_user: Callable[..., User], db_session: Session, status: TaskExecutionStatus
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, status)

    with pytest.raises(TaskExecutionNotConfirmableError):
        return_execution_to_work(db_session, adult, execution.id)


def test_return_creates_no_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    return_execution_to_work(db_session, adult, execution.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.task_execution_id == execution.id)
    )
    assert count == 0


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_confirms_award_points_exactly_once() -> None:
    """Two Adults racing to confirm the same execution must yield exactly
    one COMPLETED transition and exactly one TASK_COMPLETED PointTransaction
    -- the loser fails as a clean business error, never a double payout.
    """
    setup_session = SessionLocal()
    adult_a = User(name="Concurrent Adult A", role=ADULT)
    adult_b = User(name="Concurrent Adult B", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult_a, adult_b, child])
    setup_session.commit()
    setup_session.refresh(adult_a)
    setup_session.refresh(adult_b)
    setup_session.refresh(child)

    task = Task(title="Confirm race", reward_points=10, created_by=adult_a.id, is_active=False)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id,
        user_id=child.id,
        status=TaskExecutionStatus.AWAITING_CONFIRMATION,
        reward_points=10,
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(adult_id: uuid.UUID) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                adult = session.get(User, adult_id)
                assert adult is not None
                confirm_execution(session, adult, execution.id)
                results.append("success")
            except TaskExecutionNotConfirmableError:
                results.append("conflict")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(adult_a.id,)),
            threading.Thread(target=attempt, args=(adult_b.id,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["conflict", "success"]

        setup_session.expire_all()
        refreshed = setup_session.get(TaskExecution, execution.id)
        assert refreshed is not None
        assert refreshed.status == TaskExecutionStatus.COMPLETED

        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_execution_id == execution.id)
        )
        assert transaction_count == 1
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(task_execution_id=execution.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult_a.id, adult_b.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()


def test_concurrent_confirm_vs_return_produces_exactly_one_valid_outcome() -> None:
    """Confirm and Return racing on the same execution must yield exactly
    one winner: either COMPLETED with one PointTransaction, or IN_PROGRESS
    with none -- never both, and never an inconsistent in-between state.
    """
    setup_session = SessionLocal()
    adult_a = User(name="Concurrent Adult A", role=ADULT)
    adult_b = User(name="Concurrent Adult B", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult_a, adult_b, child])
    setup_session.commit()
    setup_session.refresh(adult_a)
    setup_session.refresh(adult_b)
    setup_session.refresh(child)

    task = Task(
        title="Confirm vs return race", reward_points=10, created_by=adult_a.id, is_active=False
    )
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id,
        user_id=child.id,
        status=TaskExecutionStatus.AWAITING_CONFIRMATION,
        reward_points=10,
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt_confirm() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                adult = session.get(User, adult_a.id)
                assert adult is not None
                confirm_execution(session, adult, execution.id)
                results.append("confirmed")
            except TaskExecutionNotConfirmableError:
                results.append("confirm-rejected")
            finally:
                session.close()

        def attempt_return() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                adult = session.get(User, adult_b.id)
                assert adult is not None
                return_execution_to_work(session, adult, execution.id)
                results.append("returned")
            except TaskExecutionNotConfirmableError:
                results.append("return-rejected")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt_confirm),
            threading.Thread(target=attempt_return),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        winners = [r for r in results if r in ("confirmed", "returned")]
        assert len(winners) == 1

        setup_session.expire_all()
        refreshed = setup_session.get(TaskExecution, execution.id)
        assert refreshed is not None

        transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.task_execution_id == execution.id)
        )

        if winners == ["confirmed"]:
            assert refreshed.status == TaskExecutionStatus.COMPLETED
            assert transaction_count == 1
        else:
            assert refreshed.status == TaskExecutionStatus.IN_PROGRESS
            assert transaction_count == 0
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(task_execution_id=execution.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult_a.id, adult_b.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
