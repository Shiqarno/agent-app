import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import (
    AssigneeNotFoundError,
    ForbiddenError,
    InvalidTransitionError,
    TaskNotFoundError,
)
from app.identity import get_current_user, require_adult
from app.models import PointTransaction, PointTransactionReason, Task, TaskStatus, User, utcnow
from app.schemas import TaskCreate, TaskReassign, TaskResponse, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_CANCELLABLE_STATUSES = frozenset(
    {TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_CONFIRMATION}
)


def _get_task_for_update(db: Session, task_id: uuid.UUID) -> Task | None:
    """Loads a Task with its row lock held for the rest of the transaction.

    Every lifecycle mutation (start/ready/confirm/cancel/reassign/edit) reads
    the current status, decides whether the transition is valid, then
    writes. Without a lock, two concurrent mutations (e.g. confirm and
    cancel on the same AWAITING_CONFIRMATION task) could both read the same
    pre-mutation status and both "succeed", leaving an inconsistent result
    (e.g. status=CANCELLED with a TASK_COMPLETED PointTransaction already
    created). FOR UPDATE serializes them: the second call blocks until the
    first commits, then re-reads the now-current status and is correctly
    rejected by the same status check every handler already had.
    """
    stmt = select(Task).where(Task.id == task_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Task]:
    stmt = (
        select(Task)
        .where(or_(Task.created_by == user.id, Task.assigned_to == user.id))
        .order_by(Task.created_at.asc())
    )
    return list(db.scalars(stmt))


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    # Same creator-or-assignee visibility rule as the list endpoint. A Task
    # that exists but isn't visible to this user reports as not-found (not
    # forbidden), so its existence isn't leaked to someone who merely knows
    # or guesses its id.
    if task is None or (task.created_by != user.id and task.assigned_to != user.id):
        raise TaskNotFoundError()
    return task


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> Task:
    assignee = db.get(User, payload.assigned_to)
    if assignee is None:
        raise AssigneeNotFoundError()

    task = Task(
        title=payload.title,
        description=payload.description,
        reward_points=payload.reward_points,
        assigned_to=payload.assigned_to,
        created_by=user.id,
        status=TaskStatus.ASSIGNED,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if task.status != TaskStatus.ASSIGNED:
        raise InvalidTransitionError(f"Cannot edit a task in status {task.status.value}")

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    task.updated_at = utcnow()

    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/reassign", response_model=TaskResponse)
def reassign_task(
    task_id: uuid.UUID,
    payload: TaskReassign,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if task.status != TaskStatus.ASSIGNED:
        raise InvalidTransitionError(f"Cannot reassign a task in status {task.status.value}")

    assignee = db.get(User, payload.assigned_to)
    if assignee is None:
        raise AssigneeNotFoundError()

    task.assigned_to = payload.assigned_to
    task.updated_at = utcnow()

    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/start", response_model=TaskResponse)
def start_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.assigned_to != user.id:
        raise ForbiddenError("This task is not assigned to you")
    if task.status != TaskStatus.ASSIGNED:
        raise InvalidTransitionError(f"Cannot start a task in status {task.status.value}")

    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/ready", response_model=TaskResponse)
def mark_task_ready(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.assigned_to != user.id:
        raise ForbiddenError("This task is not assigned to you")
    if task.status != TaskStatus.IN_PROGRESS:
        raise InvalidTransitionError(f"Cannot mark a task in status {task.status.value} as ready")

    task.status = TaskStatus.AWAITING_CONFIRMATION
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/confirm", response_model=TaskResponse)
def confirm_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if task.status != TaskStatus.AWAITING_CONFIRMATION:
        raise InvalidTransitionError(f"Cannot confirm a task in status {task.status.value}")

    task.status = TaskStatus.COMPLETED
    task.updated_at = utcnow()
    db.add(
        PointTransaction(
            user_id=task.assigned_to,
            task_id=task.id,
            amount=task.reward_points,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise InvalidTransitionError("Task has already been confirmed") from exc
    db.refresh(task)
    return task


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.created_by != user.id:
        raise ForbiddenError("You do not own this task")
    if task.status not in _CANCELLABLE_STATUSES:
        raise InvalidTransitionError(f"Cannot cancel a task in status {task.status.value}")

    # No PointTransaction is ever created here -- cancellation must never
    # award points, and the only transition that does (AWAITING_CONFIRMATION
    # -> COMPLETED via confirm_task) is unaffected by this endpoint existing.
    task.status = TaskStatus.CANCELLED
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task
