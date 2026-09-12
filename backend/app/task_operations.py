import uuid

from pydantic import ValidationError
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
from app.schemas import TaskCreate, TaskUpdate

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

# The only statuses an Adult may cancel from (see cancel_execution below) --
# a Child's own work-in-progress, not yet submitted for confirmation.
# AWAITING_CONFIRMATION is deliberately excluded: that stage already has
# its own Adult-facing resolution (Confirm/Return), and Cancel is not a
# third way to resolve it.
CANCELLABLE_EXECUTION_STATUSES = frozenset(
    {
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
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


class TaskNotFoundError(TaskOperationError):
    """No Task exists with this id."""


class TaskNotEditableError(TaskOperationError):
    """The Task has a current open execution, so its title/reward cannot be
    edited right now (Issue #28 section 5) -- an Adult must wait for the
    Child's work to reach a terminal state (via the existing Confirmation
    workflow) or a Return-to-work, not act on stale Task Details.

    Deliberately no longer raised by activate_task/deactivate_task (Issue
    #37): `Task.is_active` is a self-claim slot, independent of whatever
    executions already exist, so toggling it is never blocked by them --
    only editing the Task's own title/reward still is.
    """


class InvalidTaskInputError(TaskOperationError):
    """title/reward_points failed validation. Carries a human-readable
    message (reusing the existing TaskCreate/TaskUpdate Pydantic
    validation, Issue #28 section 6) so the Telegram adapter can show
    exactly why, without re-deriving the same rules.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ChildNotFoundError(TaskOperationError):
    """No eligible Child exists with this id for assignment (Issue #32) --
    covers both "doesn't exist" and "exists but isn't a Child", collapsed
    into one error so a crafted callback can't distinguish the two
    (matching the UserNotFoundError precedent in user_operations.py).
    """


class TaskAlreadyOpenForChildError(TaskOperationError):
    """The target Child already has an open (ASSIGNED/IN_PROGRESS/
    AWAITING_CONFIRMATION) execution of this Task (Issue #32) -- the same
    one-open-execution-per-(task,user) invariant claim_task protects,
    caught here via the same partial unique index.
    """


class TaskExecutionNotCancellableError(TaskOperationError):
    """The TaskExecution doesn't exist, or isn't ASSIGNED/IN_PROGRESS. A
    deliberately separate error from TaskExecutionNotConfirmableError above
    (rather than reusing it): the two operations require different source
    states -- Confirm/Return only ever act on AWAITING_CONFIRMATION,
    Cancel only ever acts on ASSIGNED/IN_PROGRESS -- so collapsing them
    would blur which transition was actually rejected. Same no-ownership
    shape as TaskExecutionNotConfirmableError: any Adult may cancel any
    cancellable execution, so this only ever means "doesn't exist" or
    "wrong state", never "not yours".
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


def _first_error_message(exc: ValidationError) -> str:
    message: str = exc.errors()[0]["msg"]
    # Pydantic prefixes a field_validator's own ValueError with "Value
    # error, "; the Field(gt=0) constraint message doesn't have that
    # prefix. Strip it so Telegram never shows the internal wrapper text.
    return message.removeprefix("Value error, ")


def _get_current_execution(db: Session, task_id: uuid.UUID) -> tuple[TaskExecution, User] | None:
    """The Task's current open execution and its Child, if one exists
    (Issue #28 section 4). At most one is expected in practice (a Task's
    self-claim slot is exclusive -- see claim_task), but this deliberately
    tolerates more than one row existing (e.g. a pre-existing directly-
    assigned execution alongside a Task later reactivated by an Adult) by
    picking the oldest rather than assuming uniqueness.
    """
    stmt = (
        select(TaskExecution, User)
        .join(User, User.id == TaskExecution.user_id)
        .where(
            TaskExecution.task_id == task_id,
            TaskExecution.status.in_(OPEN_EXECUTION_STATUSES),
        )
        .order_by(TaskExecution.created_at.asc())
        .limit(1)
    )
    row = db.execute(stmt).first()
    return (row[0], row[1]) if row is not None else None


def _has_open_execution(db: Session, task_id: uuid.UUID) -> bool:
    stmt = select(
        exists(
            select(TaskExecution.id).where(
                TaskExecution.task_id == task_id,
                TaskExecution.status.in_(OPEN_EXECUTION_STATUSES),
            )
        )
    )
    return bool(db.scalar(stmt))


TaskWithCurrentExecution = tuple[Task, TaskExecution | None, User | None]


def get_tasks(db: Session, user: User) -> list[TaskWithCurrentExecution]:
    """The full Task-definition catalog, each paired with its current open
    execution and Child if one exists (Issue #28 section 4) -- not Web's
    `list_tasks`, whose visibility filter scopes an Adult to Tasks they
    created or have an execution of. Telegram's Adult Tasks screen is a
    shared catalog: any Adult manages any Task (section 10, "no ownership"),
    so this deliberately shows every Task regardless of `created_by`.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    tasks = list(db.scalars(select(Task).order_by(Task.created_at.asc())))
    result: list[TaskWithCurrentExecution] = []
    for task in tasks:
        current = _get_current_execution(db, task.id)
        if current is None:
            result.append((task, None, None))
        else:
            execution, child = current
            result.append((task, execution, child))
    return result


def get_task(db: Session, user: User, task_id: uuid.UUID) -> TaskWithCurrentExecution:
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()

    current = _get_current_execution(db, task.id)
    if current is None:
        return task, None, None
    execution, child = current
    return task, execution, child


def create_task(db: Session, user: User, *, title: str, reward_points: int) -> Task:
    """Creates a new Task definition, active immediately (Issue #28 section
    6). Direct assignment is out of scope for this issue -- unlike Web's
    `POST /api/tasks`, there is no `assigned_to` path here.

    Reuses the existing `TaskCreate` Pydantic validation (title non-blank,
    reward_points > 0) rather than re-deriving the same rules -- `app.
    schemas` has no FastAPI dependency, so this stays framework-agnostic.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    try:
        payload = TaskCreate(title=title, reward_points=reward_points)
    except ValidationError as exc:
        raise InvalidTaskInputError(_first_error_message(exc)) from exc

    task = Task(
        title=payload.title,
        reward_points=payload.reward_points,
        is_active=True,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    user: User,
    task_id: uuid.UUID,
    *,
    title: str | None = None,
    reward_points: int | None = None,
) -> Task:
    """Edits title/reward_points (Issue #28 section 7). Unlike Web's `PATCH
    /api/tasks/{id}` (creator-only, no open-execution restriction), this is
    role-only (section 10, "no ownership") and refuses to edit while a
    current open execution exists (section 5) -- a genuinely different
    rule from Web's, so this is a new operation rather than a thin wrapper.

    Changing `Task.reward_points` here only ever touches the Task row --
    every existing `TaskExecution.reward_points` is an immutable snapshot
    taken at claim time and is never revisited.

    Concurrency: holds the same Task row lock `claim_task` takes, so a
    concurrent claim and this edit fully serialize -- the open-execution
    check below is guaranteed accurate for the rest of this transaction.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if _has_open_execution(db, task.id):
        raise TaskNotEditableError()

    try:
        payload = TaskUpdate(title=title, reward_points=reward_points)
    except ValidationError as exc:
        raise InvalidTaskInputError(_first_error_message(exc)) from exc

    if payload.title is not None:
        task.title = payload.title
    if payload.reward_points is not None:
        task.reward_points = payload.reward_points
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


def activate_task(db: Session, user: User, task_id: uuid.UUID) -> Task:
    """Reopens the Task's self-claim slot (Issue #28 section 8). Idempotent
    -- activating an already-active Task is a no-op success, matching the
    existing Web `activate_task` precedent.

    Deliberately independent of any current open execution (Issue #37):
    `is_active` means only "may a new self-claim happen right now", never
    whether the Task has executions at all -- an Adult may reopen the
    self-claim slot while one or more Children already have open
    executions of this Task, and doing so never touches those executions.
    The existing (task_id, user_id) open-execution uniqueness constraint
    is what continues to prevent the *same* Child from claiming twice; it
    has nothing to do with this flag.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()

    task.is_active = True
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


def deactivate_task(db: Session, user: User, task_id: uuid.UUID) -> Task:
    """Closes the Task's self-claim slot (Issue #28 section 8). Idempotent,
    same rationale as activate_task above -- deliberately independent of
    any current open execution (Issue #37): existing executions are never
    cancelled or otherwise modified by closing the slot.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()

    task.is_active = False
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


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


def cancel_execution(
    db: Session, user: User, execution_id: uuid.UUID
) -> tuple[TaskExecution, Task, User]:
    """ASSIGNED/IN_PROGRESS -> CANCELLED (an Adult withdrawing a Child's
    still-open execution), no PointTransaction -- mirrors
    return_execution_to_work's shape exactly, just with a different source
    state and destination.

    Deliberately touches nothing else: the underlying Task (`is_active`,
    reward, title) is never modified, so an already-active Task remains
    self-claimable exactly as before, and a directly-assigned Task's
    `is_active` is unaffected either way (assign_task never touched it to
    begin with). The cancelled row itself is never deleted -- it simply
    stops being "open" (CANCELLED is not in OPEN_EXECUTION_STATUSES), so
    the Child's own `/mytasks`-equivalent (get_my_tasks) naturally stops
    listing it, and the (task_id, user_id) open-execution uniqueness no
    longer blocks a fresh claim/assignment for the same pair.

    Concurrency: same row lock and same-transaction status check as
    confirm_execution/return_execution_to_work, so this cannot race a
    concurrent mark_execution_ready/confirm/return into cancelling an
    execution that has already moved to AWAITING_CONFIRMATION or beyond --
    whichever transaction's UPDATE commits first wins the row lock, and the
    loser re-reads the now-changed status and is rejected before mutating
    anything. No IntegrityError catch needed, same reasoning as
    return_execution_to_work: nothing about this transition is
    uniqueness-constrained.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    execution = _get_execution_for_update(db, execution_id)
    if execution is None or execution.status not in CANCELLABLE_EXECUTION_STATUSES:
        raise TaskExecutionNotCancellableError()

    execution.status = TaskExecutionStatus.CANCELLED
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)

    task = db.get(Task, execution.task_id)
    assert task is not None
    child = db.get(User, execution.user_id)
    assert child is not None
    return execution, task, child


def get_assignable_children(db: Session, actor: User, task_id: uuid.UUID) -> list[User]:
    """Every Child NOT already holding an open execution of this Task
    (Issue #32) -- the eligible-recipient list for direct assignment.
    Adults are never eligible (assignment is Child-only); a Child who
    already has an ASSIGNED/IN_PROGRESS/AWAITING_CONFIRMATION execution of
    this same Task is excluded, matching the one-open-execution-per-
    (task,user) invariant `assign_task` itself enforces -- a Child with
    only terminal (COMPLETED/CANCELLED) executions of this Task remains
    eligible.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()

    ineligible_ids = select(TaskExecution.user_id).where(
        TaskExecution.task_id == task_id,
        TaskExecution.status.in_(OPEN_EXECUTION_STATUSES),
    )
    stmt = (
        select(User)
        .where(User.role == UserRole.CHILD, User.id.not_in(ineligible_ids))
        .order_by(User.name.asc(), User.id.asc())
    )
    return list(db.scalars(stmt))


def assign_task(
    db: Session, actor: User, task_id: uuid.UUID, target_user: User
) -> tuple[TaskExecution, Task]:
    """Directly assigns an existing Task to a Child, creating a new
    ASSIGNED TaskExecution (Issue #32).

    Deliberately independent of `Task.is_active`: that flag means only
    "can currently be self-claimed" (see claim_task) and is never read or
    written here. The Task may be active or inactive, and may already
    have any number of other open executions for other Children -- none
    of that is touched.

    Concurrency: unlike claim_task (which locks the Task row because it
    reads-then-conditionally-writes `Task.is_active`), this operation only
    ever establishes a new uniqueness fact -- at most one open execution
    per (task_id, user_id) -- so per this project's established
    distinction between the two concurrency patterns, the existing partial
    unique index is the right (and sufficient) boundary: two concurrent
    assignments to the same Child and Task (or an assignment racing a
    self-claim) can both attempt the insert, but at most one commits,
    caught here via IntegrityError exactly like claim_task's own race
    against itself.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()
    if target_user.role != UserRole.CHILD:
        raise ChildNotFoundError()

    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()

    execution = TaskExecution(
        task_id=task.id,
        user_id=target_user.id,
        status=TaskExecutionStatus.ASSIGNED,
        reward_points=task.reward_points,
    )
    db.add(execution)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaskAlreadyOpenForChildError() from exc
    db.refresh(execution)
    db.refresh(task)
    return execution, task


def start_execution(db: Session, user: User, execution_id: uuid.UUID) -> tuple[TaskExecution, Task]:
    """ASSIGNED -> IN_PROGRESS (Issue #32): the Child's Start action on a
    directly-assigned execution. No new TaskExecution is created -- the
    existing row is updated in place, the same shape as
    mark_execution_ready's IN_PROGRESS -> AWAITING_CONFIRMATION transition.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    execution = _get_execution_for_update(db, execution_id)
    if execution is None or execution.user_id != user.id:
        raise TaskExecutionNotActionableError()
    if execution.status != TaskExecutionStatus.ASSIGNED:
        raise TaskExecutionNotActionableError()

    execution.status = TaskExecutionStatus.IN_PROGRESS
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)

    task = db.get(Task, execution.task_id)
    assert task is not None
    return execution, task
