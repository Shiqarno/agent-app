import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ChildNotFoundError, ForbiddenError, InvalidTransitionError, TaskNotFoundError
from app.identity import get_current_user, require_adult, require_child
from app.models import Task, TaskStatus, User, UserRole, utcnow
from app.schemas import TaskCreate, TaskResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Task]:
    if user.role == UserRole.ADULT:
        stmt = select(Task).where(Task.adult_id == user.id).order_by(Task.created_at.asc())
    else:
        stmt = select(Task).where(Task.child_id == user.id).order_by(Task.created_at.asc())
    return list(db.scalars(stmt))


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> Task:
    child = db.get(User, payload.child_id)
    if child is None or child.role != UserRole.CHILD:
        raise ChildNotFoundError()

    task = Task(
        title=payload.title,
        description=payload.description,
        reward_points=payload.reward_points,
        child_id=payload.child_id,
        adult_id=user.id,
        status=TaskStatus.ASSIGNED,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/start", response_model=TaskResponse)
def start_task(
    task_id: uuid.UUID, user: User = Depends(require_child), db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.child_id != user.id:
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
    task_id: uuid.UUID, user: User = Depends(require_child), db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.child_id != user.id:
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
    task_id: uuid.UUID, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise TaskNotFoundError()
    if task.adult_id != user.id:
        raise ForbiddenError("You do not own this task")
    if task.status != TaskStatus.AWAITING_CONFIRMATION:
        raise InvalidTransitionError(f"Cannot confirm a task in status {task.status.value}")

    task.status = TaskStatus.COMPLETED
    task.updated_at = utcnow()
    db.commit()
    db.refresh(task)
    return task
