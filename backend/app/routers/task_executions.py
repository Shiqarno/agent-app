import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import (
    AssigneeNotFoundError,
    ForbiddenError,
    InvalidTransitionError,
    TaskExecutionNotFoundError,
)
from app.identity import get_current_user
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    utcnow,
)
from app.schemas import TaskExecutionResponse, TaskReassign

router = APIRouter(prefix="/api/task-executions", tags=["task-executions"])

_CANCELLABLE_STATUSES = frozenset(
    {
        TaskExecutionStatus.ASSIGNED,
        TaskExecutionStatus.IN_PROGRESS,
        TaskExecutionStatus.AWAITING_CONFIRMATION,
    }
)


def _get_execution_for_update(db: Session, execution_id: uuid.UUID) -> TaskExecution | None:
    """Loads a TaskExecution with its row lock held for the rest of the
    transaction -- see Task's former `_get_task_for_update` (Issue #17) for
    the full rationale. Needed here for the same reason: confirm-vs-cancel
    and reassign-vs-start races on the same execution must serialize rather
    than both apparently succeeding.
    """
    stmt = select(TaskExecution).where(TaskExecution.id == execution_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _visible_execution(db: Session, execution_id: uuid.UUID, user: User) -> TaskExecution | None:
    """A TaskExecution is visible to `user` if they own it, or they created
    the Task it belongs to (the same relationship this codebase always
    expresses as an explicit join, never an ORM `relationship()`).
    """
    stmt = (
        select(TaskExecution)
        .join(Task, Task.id == TaskExecution.task_id)
        .where(
            TaskExecution.id == execution_id,
            or_(TaskExecution.user_id == user.id, Task.created_by == user.id),
        )
    )
    return db.scalars(stmt).one_or_none()


@router.get("", response_model=list[TaskExecutionResponse])
def list_task_executions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TaskExecution]:
    stmt = (
        select(TaskExecution)
        .join(Task, Task.id == TaskExecution.task_id)
        .where(or_(TaskExecution.user_id == user.id, Task.created_by == user.id))
        .order_by(TaskExecution.created_at.asc())
    )
    return list(db.scalars(stmt))


@router.get("/{execution_id}", response_model=TaskExecutionResponse)
def get_task_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _visible_execution(db, execution_id, user)
    if execution is None:
        raise TaskExecutionNotFoundError()
    return execution


@router.post("/{execution_id}/start", response_model=TaskExecutionResponse)
def start_task_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _get_execution_for_update(db, execution_id)
    if execution is None:
        raise TaskExecutionNotFoundError()
    if execution.user_id != user.id:
        raise ForbiddenError("This task execution does not belong to you")
    if execution.status != TaskExecutionStatus.ASSIGNED:
        raise InvalidTransitionError(
            f"Cannot start an execution in status {execution.status.value}"
        )

    execution.status = TaskExecutionStatus.IN_PROGRESS
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/ready", response_model=TaskExecutionResponse)
def mark_task_execution_ready(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _get_execution_for_update(db, execution_id)
    if execution is None:
        raise TaskExecutionNotFoundError()
    if execution.user_id != user.id:
        raise ForbiddenError("This task execution does not belong to you")
    if execution.status != TaskExecutionStatus.IN_PROGRESS:
        raise InvalidTransitionError(
            f"Cannot mark an execution in status {execution.status.value} as ready"
        )

    execution.status = TaskExecutionStatus.AWAITING_CONFIRMATION
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/confirm", response_model=TaskExecutionResponse)
def confirm_task_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _get_execution_for_update(db, execution_id)
    if execution is None:
        raise TaskExecutionNotFoundError()
    task = db.get(Task, execution.task_id)
    if task is None or task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if execution.status != TaskExecutionStatus.AWAITING_CONFIRMATION:
        raise InvalidTransitionError(
            f"Cannot confirm an execution in status {execution.status.value}"
        )

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
        raise InvalidTransitionError("Task execution has already been confirmed") from exc
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/cancel", response_model=TaskExecutionResponse)
def cancel_task_execution(
    execution_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _get_execution_for_update(db, execution_id)
    if execution is None:
        raise TaskExecutionNotFoundError()
    task = db.get(Task, execution.task_id)
    if task is None or task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if execution.status not in _CANCELLABLE_STATUSES:
        raise InvalidTransitionError(
            f"Cannot cancel an execution in status {execution.status.value}"
        )

    # No PointTransaction is ever created here -- cancellation must never
    # award points, and the only transition that does (AWAITING_CONFIRMATION
    # -> COMPLETED via confirm) is unaffected by this endpoint existing.
    execution.status = TaskExecutionStatus.CANCELLED
    execution.updated_at = utcnow()
    db.commit()
    db.refresh(execution)
    return execution


@router.post("/{execution_id}/reassign", response_model=TaskExecutionResponse)
def reassign_task_execution(
    execution_id: uuid.UUID,
    payload: TaskReassign,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskExecution:
    execution = _get_execution_for_update(db, execution_id)
    if execution is None:
        raise TaskExecutionNotFoundError()
    task = db.get(Task, execution.task_id)
    if task is None or task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if execution.status != TaskExecutionStatus.ASSIGNED:
        raise InvalidTransitionError(
            f"Cannot reassign an execution in status {execution.status.value}"
        )

    assignee = db.get(User, payload.assigned_to)
    if assignee is None:
        raise AssigneeNotFoundError()

    execution.user_id = payload.assigned_to
    execution.updated_at = utcnow()

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise InvalidTransitionError("That user already has an execution for this task") from exc
    db.refresh(execution)
    return execution
