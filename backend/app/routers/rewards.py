import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import InsufficientPointsError, RewardNotFoundError
from app.identity import get_current_user, require_adult
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    User,
    utcnow,
)
from app.schemas import RewardCreate, RewardRedemptionResponse, RewardResponse, RewardUpdate

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


@router.post(
    "/{reward_id}/redeem",
    response_model=RewardRedemptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def redeem_reward(
    reward_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RewardRedemption:
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    # Lock the current user's row for the duration of this transaction so that
    # concurrent redemption attempts for the same user are serialized. A plain
    # SELECT ... FOR UPDATE (not Session.get, which may short-circuit via the
    # identity map) guarantees a real round-trip that acquires the row lock.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()

    balance = db.scalar(
        select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
            PointTransaction.user_id == user.id
        )
    )
    # COALESCE guarantees a non-null row from this aggregate query.
    assert balance is not None
    if balance < reward.cost_points:
        raise InsufficientPointsError()

    redemption_id = uuid.uuid4()
    redemption = RewardRedemption(
        id=redemption_id,
        reward_id=reward.id,
        user_id=user.id,
        cost_points=reward.cost_points,
    )
    db.add(redemption)
    # Flush (not commit) so the redemption row exists before the FK-referencing
    # insert below; both statements still land in the same open transaction and
    # commit together.
    db.flush()
    db.add(
        PointTransaction(
            user_id=user.id,
            redemption_id=redemption_id,
            amount=-reward.cost_points,
            reason=PointTransactionReason.REWARD_REDEEMED,
        )
    )
    db.commit()
    db.refresh(redemption)
    return redemption
