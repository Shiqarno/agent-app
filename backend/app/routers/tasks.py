import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import (
    AssigneeNotFoundError,
    ForbiddenError,
    TaskAlreadyClaimedError,
    TaskInactiveError,
    TaskNotFoundError,
)
from app.identity import get_current_user, require_adult
from app.models import Task, TaskExecution, User, UserRole, utcnow
from app.schemas import TaskCreate, TaskExecutionResponse, TaskResponse, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _get_task_for_update(db: Session, task_id: uuid.UUID) -> Task | None:
    """Loads a Task with its row lock held for the rest of the transaction.

    `claim` reads `is_active` then decides whether to create a TaskExecution.
    Without a lock, a concurrent `PATCH .../deactivate` could commit between
    that read and the execution insert, leaving an execution for a Task that
    -- by the time either transaction is done -- is inactive. Postgres's
    ordinary `UPDATE` (issued by `update_task` when it flips `is_active`)
    always takes an implicit row lock, so this `SELECT ... FOR UPDATE` here
    is enough to fully serialize the two: whichever transaction gets to this
    Task row first makes the other wait and then see its committed result.
    """
    stmt = select(Task).where(Task.id == task_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def _visibility_filter(user: User) -> ColumnElement[bool]:
    """A Task is visible to `user` if any of:

    - they created it (every Adult sees their own Task definitions);
    - they have an execution of it (an Adult or Child who has claimed it, or
      been directly assigned it, keeps seeing it regardless of is_active);
    - they're a Child and it's an active Task they haven't touched yet (the
      "Available Tasks" browsing case -- Adults do not get this privilege
      over each other's Task definitions).
    """
    has_execution = exists(
        select(TaskExecution.id).where(
            TaskExecution.task_id == Task.id, TaskExecution.user_id == user.id
        )
    )
    conditions = [Task.created_by == user.id, has_execution]
    if user.role == UserRole.CHILD:
        conditions.append(Task.is_active.is_(True))
    return or_(*conditions)


@router.get("", response_model=list[TaskResponse])
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Task]:
    stmt = select(Task).where(_visibility_filter(user)).order_by(Task.created_at.asc())
    return list(db.scalars(stmt))


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    stmt = select(Task).where(Task.id == task_id, _visibility_filter(user))
    task = db.scalars(stmt).one_or_none()
    if task is None:
        raise TaskNotFoundError()
    return task


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> Task:
    if payload.assigned_to is not None and db.get(User, payload.assigned_to) is None:
        raise AssigneeNotFoundError()

    task = Task(
        title=payload.title,
        description=payload.description,
        reward_points=payload.reward_points,
        is_active=True,
        created_by=user.id,
    )
    db.add(task)
    db.flush()

    if payload.assigned_to is not None:
        db.add(
            TaskExecution(
                task_id=task.id,
                user_id=payload.assigned_to,
                reward_points=task.reward_points,
            )
        )

    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: User = Depends(require_adult),
    db: Session = Depends(get_db),
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.created_by != user.id:
        raise ForbiddenError("You do not own this task")

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.reward_points is not None:
        task.reward_points = payload.reward_points
    if payload.is_active is not None:
        task.is_active = payload.is_active
    task.updated_at = utcnow()

    db.commit()
    db.refresh(task)
    return task


@router.post(
    "/{task_id}/claim", response_model=TaskExecutionResponse, status_code=status.HTTP_201_CREATED
)
def claim_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TaskExecution:
    if user.role != UserRole.CHILD:
        raise ForbiddenError("Only a Child can claim a task")

    task = _get_task_for_update(db, task_id)
    if task is None:
        raise TaskNotFoundError()
    if not task.is_active:
        raise TaskInactiveError()

    execution = TaskExecution(task_id=task.id, user_id=user.id, reward_points=task.reward_points)
    db.add(execution)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TaskAlreadyClaimedError() from exc
    db.refresh(execution)
    return execution
