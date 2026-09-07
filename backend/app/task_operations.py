import uuid

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
    utcnow,
)

# Mirrors the frontend's OPEN_EXECUTION_STATUSES (TasksPage.tsx /
# TaskDetailsPage.tsx): the only statuses that represent a still-open
# TaskExecution. Terminal (COMPLETED/CANCELLED) executions must never
# suppress a Task's future availability or appear in My Tasks.
OPEN_EXECUTION_STATUSES = frozenset(
    {
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.AWAITING_CONFIRMATION,
    }
)


class TaskOperationError(Exception):
    """Base for every Task/TaskExecution Application-layer failure
    (Issue #24). Framework-agnostic on purpose -- this module knows nothing
    about FastAPI or the Telegram bot library; each adapter that calls it is
    responsible for translating these into its own presentation.
    """


class NotAChildError(TaskOperationError):
    """Only a Child may perform this Task operation."""


class TaskNotClaimableError(TaskOperationError):
    """The Task doesn't exist, isn't active, or the current User already
    has an open execution of it -- i.e. it cannot currently be claimed.
    Deliberately one error for all three cases: which one applies is not
    something the caller needs (or should trust from stale client state) to
    distinguish.
    """


class TaskExecutionNotActionableError(TaskOperationError):
    """The TaskExecution doesn't exist, doesn't belong to the current User,
    or isn't in the lifecycle state required for the requested transition.
    """


class NotAnAdultError(TaskOperationError):
    """Only an Adult may perform this Task Confirmation operation."""


class TaskExecutionNotConfirmableError(TaskOperationError):
    """The TaskExecution doesn't exist, or isn't in AWAITING_CONFIRMATION.
    Deliberately no ownership dimension here (Issue #25 section 9): unlike
    `TaskExecutionNotActionableError` above (which also checks the calling
    User owns the execution -- that rule is for a Child acting on their own
    work), any Adult may confirm/return any awaiting execution, so this
    error only ever means "doesn't exist" or "wrong state".
    """


def _get_task_for_update(db: Session, task_id: uuid.UUID) -> Task | None:
    """Loads a Task with its row lock held for the rest of the transaction.
    Same rationale as routers.tasks._get_task_for_update (Issue #17/#19):
    `claim_task` reads `is_active` then decides whether to create a
    TaskExecution, so this must serialize against a concurrent claim or
    deactivation of the same Task.
    """
    stmt = select(Task).where(Task.id == task_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _get_execution_for_update(db: Session, execution_id: uuid.UUID) -> TaskExecution | None:
    """Loads a TaskExecution with its row lock held for the rest of the
    transaction. Same rationale as
    routers.task_executions._get_execution_for_update (Issue #17).
    """
    stmt = select(TaskExecution).where(TaskExecution.id == execution_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_available_tasks(db: Session, user: User) -> list[Task]:
    """Active Task definitions the Child can currently self-claim.

    Not simply `Task.is_active = true` (Issue #24 spec section 10): a Task
    reactivated while this same User still holds an open execution of it
    must not be offered again, even though `is_active` is true -- claiming
    it would immediately violate the one-open-execution-per-(task,user)
    invariant. Terminal (COMPLETED/CANCELLED) executions never suppress
    availability -- this is the same invariant the frontend bug fix
    (OPEN_EXECUTION_STATUSES) enforces for the Web UI.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    has_open_execution = exists(
        select(TaskExecution.id).where(
            TaskExecution.task_id == Task.id,
            TaskExecution.user_id == user.id,
            TaskExecution.status.in_(OPEN_EXECUTION_STATUSES),
        )
    )
    stmt = (
        select(Task)
        .where(Task.is_active.is_(True), ~has_open_execution)
        .order_by(Task.created_at.asc())
    )
    return list(db.scalars(stmt))


def claim_task(db: Session, user: User, task_id: uuid.UUID) -> tuple[TaskExecution, Task]:
    """Claims a Task and starts it in one atomic step (Issue #24 section 2):
    unlike the Web claim endpoint (which creates an ASSIGNED execution and
    requires a separate `/start` call), Telegram's Take has no separate
    Start step, so the execution is created directly as IN_PROGRESS.

    Concurrency: holds the same Task row lock as the Web claim endpoint, so
    a claim and a concurrent deactivation/claim of the same Task fully
    serialize. The partial unique index on (task_id, user_id) for open
    statuses is the final integrity boundary for the "no second open
    execution" rule, caught here via IntegrityError exactly like the Web
    endpoint's own claim -- deliberately no additional locking or
    idempotency infrastructure beyond what already protects Task/
    TaskExecution.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    task = _get_task_for_update(db, task_id)
    if task is None or not task.is_active:
        raise TaskNotClaimableError()

    execution = TaskExecution(
        task_id=task.id,
        user_id=user.id,
        status=TaskExecutionStatus.IN_PROGRESS,
        reward_points=task.reward_points,
    )
    db.add(execution)
    task.is_active = False
    task.updated_at = utcnow()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaskNotClaimableError() from exc
    db.refresh(execution)
    db.refresh(task)
    return execution, task


def get_my_tasks(db: Session, user: User) -> list[tuple[TaskExecution, Task]]:
    """The current User's own non-terminal TaskExecutions (Issue #24
    section 3), paired with their Task for display (title isn't stored on
    TaskExecution; reward_points comes from the execution's own immutable
    snapshot, not the Task).
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    stmt = (
        select(TaskExecution, Task)
        .join(Task, Task.id == TaskExecution.task_id)
        .where(
            TaskExecution.user_id == user.id,
            TaskExecution.status.in_(OPEN_EXECUTION_STATUSES),
        )
        .order_by(TaskExecution.created_at.asc())
    )
    return [(execution, task) for execution, task in db.execute(stmt).all()]


def mark_execution_ready(
    db: Session, user: User, execution_id: uuid.UUID
) -> tuple[TaskExecution, Task]:
    """IN_PROGRESS -> AWAITING_CONFIRMATION (Issue #24 section 4/12). Never
    completes the execution, never creates a PointTransaction -- point
    transaction creation stays tied to the existing AWAITING_CONFIRMATION ->
    COMPLETED confirm step, unaffected by this operation.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    execution = _get_execution_for_update(db, execution_id)
    if execution is None or execution.user_id != user.id:
        raise TaskExecutionNotActionableError()
    if execution.status != TaskExecutionStatus.IN_PROGRESS:
        raise TaskExecutionNotActionableError()

    execution.status = TaskExecutionStatus.AWAITING_CONFIRMATION
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)

    task = db.get(Task, execution.task_id)
    assert task is not None  # a TaskExecution's Task is never deleted
    return execution, task


def get_pending_confirmations(db: Session, user: User) -> list[tuple[TaskExecution, Task, User]]:
    """Executions currently awaiting Adult confirmation (Issue #25 section
    12), paired with their Task and Child for presentation. Deliberately no
    ownership filter -- see confirm_execution/return_execution_to_work: any
    Adult sees every awaiting execution, not just ones for Tasks they
    created.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    stmt = (
        select(TaskExecution, Task, User)
        .join(Task, Task.id == TaskExecution.task_id)
        .join(User, User.id == TaskExecution.user_id)
        .where(TaskExecution.status == TaskExecutionStatus.AWAITING_CONFIRMATION)
        .order_by(TaskExecution.created_at.asc())
    )
    return [(execution, task, child) for execution, task, child in db.execute(stmt).all()]


def confirm_execution(
    db: Session, user: User, execution_id: uuid.UUID
) -> tuple[TaskExecution, Task, User]:
    """AWAITING_CONFIRMATION -> COMPLETED, plus exactly one TASK_COMPLETED
    PointTransaction, atomically (Issue #25 section 5/13).

    Authorization is deliberately role-only, not ownership-based (section
    9): unlike the Web confirm endpoint (routers/task_executions.py, which
    requires `task.created_by == user.id`), any Adult may confirm any
    awaiting execution here -- there is no Adult<->Child ownership model.
    This is why this function is not a thin wrapper around the Web
    endpoint: the two have genuinely different authorization semantics, and
    the Web endpoint's existing (tested, public) contract is left
    untouched. What *is* reused is the shape of the underlying mechanics
    (row lock, status check, PointTransaction creation, the
    task_execution_id+reason unique constraint as the concurrency
    backstop) -- the same pattern as the Web endpoint's own confirm.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    execution = _get_execution_for_update(db, execution_id)
    if execution is None or execution.status != TaskExecutionStatus.AWAITING_CONFIRMATION:
        raise TaskExecutionNotConfirmableError()

    execution.status = TaskExecutionStatus.COMPLETED
    execution.updated_at = utcnow()
    db.add(
        PointTransaction(
            user_id=execution.user_id,
            task_execution_id=execution.id,
            amount=execution.reward_points,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaskExecutionNotConfirmableError() from exc
    db.refresh(execution)

    task = db.get(Task, execution.task_id)
    assert task is not None
    child = db.get(User, execution.user_id)
    assert child is not None
    return execution, task, child


def return_execution_to_work(
    db: Session, user: User, execution_id: uuid.UUID
) -> tuple[TaskExecution, Task, User]:
    """AWAITING_CONFIRMATION -> IN_PROGRESS, no PointTransaction (Issue #25
    section 7/14). Same row lock as confirm_execution, so a concurrent
    Confirm/Return race on the same execution fully serializes: whichever
    transaction gets the lock first commits its transition, and the other
    re-reads the now-changed status and is rejected before mutating
    anything -- no IntegrityError catch needed here since (unlike
    PointTransaction) nothing about this transition is uniqueness-
    constrained.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    execution = _get_execution_for_update(db, execution_id)
    if execution is None or execution.status != TaskExecutionStatus.AWAITING_CONFIRMATION:
        raise TaskExecutionNotConfirmableError()

    execution.status = TaskExecutionStatus.IN_PROGRESS
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)

    task = db.get(Task, execution.task_id)
    assert task is not None
    child = db.get(User, execution.user_id)
    assert child is not None
    return execution, task, child
