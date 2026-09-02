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
from app.schemas import TaskCreate, TaskResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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


@router.post("/{task_id}/start", response_model=TaskResponse)
def start_task(
    task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
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
    task = db.get(Task, task_id)
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
    task = db.get(Task, task_id)
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
