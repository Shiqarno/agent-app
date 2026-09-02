import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import RewardNotFoundError
from app.identity import get_current_user, require_adult
from app.models import Reward, User, utcnow
from app.schemas import RewardCreate, RewardResponse, RewardUpdate

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


@router.get("", response_model=list[RewardResponse])
def list_rewards(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Reward]:
    stmt = select(Reward).order_by(Reward.name.asc(), Reward.id.asc())
    return list(db.scalars(stmt))


@router.post("", response_model=RewardResponse, status_code=status.HTTP_201_CREATED)
def create_reward(
    payload: RewardCreate, user: User = Depends(require_adult), db: Session = Depends(get_db)
) -> Reward:
    reward = Reward(
        name=payload.name,
        description=payload.description,
        cost_points=payload.cost_points,
        created_by=user.id,
    )
    db.add(reward)
    db.commit()
    db.refresh(reward)
    return reward


@router.patch("/{reward_id}", response_model=RewardResponse)
def update_reward(
    reward_id: uuid.UUID,
    payload: RewardUpdate,
    user: User = Depends(require_adult),
    db: Session = Depends(get_db),
) -> Reward:
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    if payload.name is not None:
        reward.name = payload.name
    if payload.description is not None:
        reward.description = payload.description
    if payload.cost_points is not None:
        reward.cost_points = payload.cost_points
    reward.updated_at = utcnow()

    db.commit()
    db.refresh(reward)
    return reward
