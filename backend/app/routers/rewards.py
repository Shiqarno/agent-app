import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reward_operations
from app.db import get_db
from app.errors import InsufficientPointsError, RewardNotFoundError
from app.identity import get_current_user, require_adult
from app.models import Reward, RewardRedemption, User
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
    """Business logic lives in app.reward_operations (Issue #30) -- shared
    with Telegram's Adult Reward management, which needs the exact same
    behavior (Adult-only, no ownership beyond audit metadata).
    """
    return reward_operations.create_reward(
        db,
        user,
        name=payload.name,
        description=payload.description,
        cost_points=payload.cost_points,
    )


@router.patch("/{reward_id}", response_model=RewardResponse)
def update_reward(
    reward_id: uuid.UUID,
    payload: RewardUpdate,
    user: User = Depends(require_adult),
    db: Session = Depends(get_db),
) -> Reward:
    """Business logic lives in app.reward_operations (Issue #30) -- see
    create_reward above. The partial-update semantics (a field left as
    None on the payload is left untouched) are unchanged.
    """
    try:
        return reward_operations.update_reward(
            db,
            user,
            reward_id,
            name=payload.name,
            description=payload.description,
            cost_points=payload.cost_points,
        )
    except reward_operations.RewardNotFoundError as exc:
        raise RewardNotFoundError() from exc


@router.post(
    "/{reward_id}/redeem",
    response_model=RewardRedemptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def redeem_reward(
    reward_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RewardRedemption:
    """Business logic lives in app.reward_operations (Issue #26) -- shared
    with the Telegram Child Rewards workflow, which needs the exact same
    behavior (no role/ownership restriction, current-cost snapshot, User-
    row-locked balance check). This endpoint only translates the
    Application layer's framework-agnostic errors into this API's existing
    HTTP error shape.
    """
    try:
        redemption, _, _ = reward_operations.redeem_reward(db, user, reward_id)
    except reward_operations.RewardNotFoundError as exc:
        raise RewardNotFoundError() from exc
    except reward_operations.InsufficientPointsError as exc:
        raise InsufficientPointsError() from exc
    return redemption
