import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Task, TaskExecution, TaskExecutionStatus, User, UserRole
from app.task_operations import (
    InvalidTaskInputError,
    NotAnAdultError,
    TaskNotClaimableError,
    TaskNotEditableError,
    TaskNotFoundError,
    activate_task,
    claim_task,
    create_task,
    deactivate_task,
    get_task,
    get_tasks,
    update_task,
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
# get_tasks / get_task
# =========================================================================================


def test_adult_can_list_tasks(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult)

    items = get_tasks(db_session, adult)

    assert [t.id for t, _, _ in items] == [task.id]


def test_any_adult_sees_tasks_created_by_another_adult(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Issue #28 section 10: no ownership -- the catalog is shared."""
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    task = _make_task(db_session, creator)

    items = get_tasks(db_session, other_adult)

    assert [t.id for t, _, _ in items] == [task.id]


def test_get_tasks_rejects_a_child(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        get_tasks(db_session, child)


def test_get_tasks_shows_current_open_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD, "Alex")
    task = _make_task(db_session, adult, is_active=False)
    execution = _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    [(_, returned_execution, returned_child)] = get_tasks(db_session, adult)

    assert returned_execution is not None
    assert returned_execution.id == execution.id
    assert returned_child is not None
    assert returned_child.id == child.id


def test_get_tasks_completed_execution_does_not_show_as_current(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, TaskExecutionStatus.COMPLETED)

    [(_, execution, child_result)] = get_tasks(db_session, adult)

    assert execution is None
    assert child_result is None


def test_get_tasks_cancelled_execution_does_not_show_as_current(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)
    _make_execution(db_session, task, child, TaskExecutionStatus.CANCELLED)

    [(_, execution, child_result)] = get_tasks(db_session, adult)

    assert execution is None
    assert child_result is None


def test_adult_can_open_an_existing_task(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult)

    returned_task, execution, child = get_task(db_session, adult, task.id)

    assert returned_task.id == task.id
    assert execution is None
    assert child is None


def test_get_task_nonexistent_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(TaskNotFoundError):
        get_task(db_session, adult, uuid.uuid4())


# =========================================================================================
# create_task
# =========================================================================================


def test_adult_can_create_a_task(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    task = create_task(db_session, adult, title="Clean room", reward_points=20)

    assert task.title == "Clean room"
    assert task.reward_points == 20
    assert task.is_active is True
    assert task.created_by == adult.id


def test_child_cannot_create_a_task(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        create_task(db_session, child, title="Clean room", reward_points=20)


def test_create_task_rejects_a_blank_title(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidTaskInputError):
        create_task(db_session, adult, title="   ", reward_points=20)


def test_create_task_rejects_non_positive_reward(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidTaskInputError):
        create_task(db_session, adult, title="Clean room", reward_points=0)


def test_create_task_error_message_is_human_readable(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidTaskInputError) as exc_info:
        create_task(db_session, adult, title="", reward_points=20)

    assert "Value error" not in exc_info.value.message


# =========================================================================================
# update_task
# =========================================================================================


def test_adult_can_edit_a_task(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult, title="Clean room", reward_points=20)

    updated = update_task(db_session, adult, task.id, title="Tidy room", reward_points=25)

    assert updated.title == "Tidy room"
    assert updated.reward_points == 25


def test_any_adult_can_edit_a_task_created_by_another_adult(
    make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    task = _make_task(db_session, creator)

    updated = update_task(db_session, other_adult, task.id, title="Renamed")

    assert updated.title == "Renamed"


def test_child_cannot_edit_a_task(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult)

    with pytest.raises(NotAnAdultError):
        update_task(db_session, child, task.id, title="Hacked")


def test_edit_nonexistent_task_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(TaskNotFoundError):
        update_task(db_session, adult, uuid.uuid4(), title="New name")


def test_edit_is_rejected_when_an_open_execution_exists(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=False)
    _make_execution(db_session, task, child, TaskExecutionStatus.IN_PROGRESS)

    with pytest.raises(TaskNotEditableError):
        update_task(db_session, adult, task.id, title="New name")


def test_edit_rejects_invalid_input(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult)

    with pytest.raises(InvalidTaskInputError):
        update_task(db_session, adult, task.id, reward_points=-5)


def test_changing_task_reward_does_not_change_existing_execution_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, reward_points=20)
    execution = _make_execution(
        db_session, task, child, TaskExecutionStatus.COMPLETED, reward_points=20
    )

    update_task(db_session, adult, task.id, reward_points=99)

    db_session.refresh(execution)
    assert execution.reward_points == 20


# =========================================================================================
# activate_task / deactivate_task
# =========================================================================================


def test_adult_can_activate_an_inactive_task_without_an_open_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult, is_active=False)

    activated = activate_task(db_session, adult, task.id)

    assert activated.is_active is True


def test_adult_can_deactivate_an_active_task_without_an_open_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult, is_active=True)

    deactivated = deactivate_task(db_session, adult, task.id)

    assert deactivated.is_active is False


def test_child_cannot_activate_a_task(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=False)

    with pytest.raises(NotAnAdultError):
        activate_task(db_session, child, task.id)


def test_child_cannot_deactivate_a_task(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=True)

    with pytest.raises(NotAnAdultError):
        deactivate_task(db_session, child, task.id)


def test_activate_is_rejected_when_an_open_execution_exists(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=False)
    _make_execution(db_session, task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    with pytest.raises(TaskNotEditableError):
        activate_task(db_session, adult, task.id)


def test_deactivate_is_rejected_when_an_open_execution_exists(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=True)
    _make_execution(db_session, task, child, TaskExecutionStatus.ASSIGNED)

    with pytest.raises(TaskNotEditableError):
        deactivate_task(db_session, adult, task.id)


def test_activate_is_idempotent(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    task = _make_task(db_session, adult, is_active=True)

    activated = activate_task(db_session, adult, task.id)

    assert activated.is_active is True


def test_deactivate_ignores_a_completed_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=True)
    _make_execution(db_session, task, child, TaskExecutionStatus.COMPLETED)

    deactivated = deactivate_task(db_session, adult, task.id)

    assert deactivated.is_active is False


def test_deactivate_ignores_a_cancelled_execution(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    task = _make_task(db_session, adult, is_active=True)
    _make_execution(db_session, task, child, TaskExecutionStatus.CANCELLED)

    deactivated = deactivate_task(db_session, adult, task.id)

    assert deactivated.is_active is False


# =========================================================================================
# Concurrency / stale state
# =========================================================================================


def test_concurrent_claim_vs_deactivate_never_leaves_an_inconsistent_state() -> None:
    """A Child's Take and an Adult's Deactivate racing on the same Task must
    fully serialize via the shared Task row lock (Issue #28 section 13):
    whichever transaction gets the lock first wins, and the other re-reads
    the now-committed result and is cleanly rejected -- never both
    "succeeding" (an execution created on a Task the Adult believes they
    just deactivated), and never a partial/inconsistent state.
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

    try:
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def attempt_claim() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                user = session.get(User, child.id)
                assert user is not None
                claim_task(session, user, task.id)
                results["claim"] = "success"
            except TaskNotClaimableError:
                results["claim"] = "rejected"
            finally:
                session.close()

        def attempt_deactivate() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                user = session.get(User, adult.id)
                assert user is not None
                deactivate_task(session, user, task.id)
                results["deactivate"] = "success"
            except TaskNotEditableError:
                results["deactivate"] = "rejected"
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt_claim),
            threading.Thread(target=attempt_deactivate),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        setup_session.expire_all()
        execution_count = setup_session.query(TaskExecution).filter_by(task_id=task.id).count()
        refreshed_task = setup_session.get(Task, task.id)
        assert refreshed_task is not None
        assert refreshed_task.is_active is False

        if results["claim"] == "success":
            assert results["deactivate"] == "rejected"
            assert execution_count == 1
        else:
            assert results["claim"] == "rejected"
            assert results["deactivate"] == "success"
            assert execution_count == 0
    finally:
        setup_session.rollback()
        setup_session.query(TaskExecution).filter_by(task_id=task.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
