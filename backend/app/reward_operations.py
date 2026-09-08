import uuid

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    User,
    UserRole,
    utcnow,
)
from app.schemas import RewardCreate, RewardUpdate


class RewardOperationError(Exception):
    """Base for every Reward/Redemption Application-layer failure
    (Issue #26). Framework-agnostic on purpose -- this module knows nothing
    about FastAPI or the Telegram bot library.
    """


class RewardNotFoundError(RewardOperationError):
    """No Reward exists with this id."""


class InsufficientPointsError(RewardOperationError):
    """The User's current ledger balance is less than the Reward's current
    cost.
    """


class NotAnAdultError(RewardOperationError):
    """Only an Adult may manage the Reward catalog (create/update)."""


class InvalidRewardInputError(RewardOperationError):
    """name/cost_points failed validation. Carries a human-readable message
    (reusing the existing RewardCreate/RewardUpdate Pydantic validation,
    matching Issue #28's TaskCreate/TaskUpdate reuse) so the Telegram
    adapter can show exactly why, without re-deriving the rules.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _first_error_message(exc: ValidationError) -> str:
    message: str = exc.errors()[0]["msg"]
    # Pydantic prefixes a field_validator's own ValueError with "Value
    # error, "; the Field(gt=0) constraint message doesn't have that
    # prefix. Strip it so Telegram never shows the internal wrapper text.
    return message.removeprefix("Value error, ")


def get_balance(db: Session, user_id: uuid.UUID) -> int:
    """The current ledger balance -- the same COALESCE(SUM(amount)) query as
    the existing Web `GET /api/points/balance` (routers/points.py) and the
    Web redeem endpoint's own balance check (routers/rewards.py). The point
    ledger stays the single source of truth; there is no mutable balance
    column anywhere.
    """
    balance = db.scalar(
        select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
            PointTransaction.user_id == user_id
        )
    )
    assert balance is not None  # COALESCE guarantees a non-null row
    return balance


def get_rewards(db: Session, user: User) -> tuple[list[Reward], int]:
    """The global Reward catalog, plus the current User's balance so a
    caller can render affordability without a second round trip (Issue #26
    section "Rewards list"). Not scoped by role or ownership -- every User
    sees the same catalog, exactly like the existing Web `GET /api/rewards`.
    """
    rewards = list(db.scalars(select(Reward).order_by(Reward.name.asc(), Reward.id.asc())))
    return rewards, get_balance(db, user.id)


def redeem_reward(
    db: Session, user: User, reward_id: uuid.UUID
) -> tuple[RewardRedemption, Reward, int]:
    """Atomically redeems a Reward at its CURRENT cost (Issue #26).

    Extracted from the existing Web `POST /api/rewards/{id}/redeem`
    (routers/rewards.py), which already implements exactly this behavior
    with no role/ownership restriction -- the Web router now calls this
    directly instead of duplicating the logic (see routers/rewards.py for
    the HTTP-error translation). Deliberately no Child-only check here:
    "Adult doesn't get a Get action" (Issue #26's Authorization section) is
    a Telegram UX decision, not a new Application-layer authorization rule
    -- adding one here would change the Web endpoint's existing, tested
    contract, which already allows any authenticated User to redeem.

    Concurrency: locks the User row for the duration of the transaction
    (not the Reward -- two *different* Rewards redeemed by the same user
    must still serialize against their shared balance), exactly as the
    existing Web implementation did. The balance check and the write are
    therefore atomic with respect to any other redemption by this same
    User; a concurrent redemption of a different Reward, or a concurrent
    point-earning event, is unaffected -- same scope as the pre-existing
    guarantee.
    """
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    # A plain SELECT ... FOR UPDATE (not Session.get, which may
    # short-circuit via the identity map) guarantees a real round-trip that
    # acquires the row lock.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()

    balance = get_balance(db, user.id)
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

    return redemption, reward, balance - reward.cost_points


def create_reward(
    db: Session, actor: User, *, name: str, description: str | None, cost_points: int
) -> Reward:
    """Creates a new Reward (Issue #30). Extracted from the existing Web
    `POST /api/rewards` (routers/rewards.py), which already implements
    exactly this behavior -- Adult-only, no ownership beyond audit metadata
    -- so the Web router now calls this directly instead of duplicating the
    logic. Reuses the existing `RewardCreate` Pydantic validation (name
    non-blank, cost_points > 0) rather than re-deriving the same rules.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    try:
        payload = RewardCreate(name=name, description=description, cost_points=cost_points)
    except ValidationError as exc:
        raise InvalidRewardInputError(_first_error_message(exc)) from exc

    reward = Reward(
        name=payload.name,
        description=payload.description,
        cost_points=payload.cost_points,
        created_by=actor.id,
    )
    db.add(reward)
    db.commit()
    db.refresh(reward)
    return reward


def update_reward(
    db: Session,
    actor: User,
    reward_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    cost_points: int | None = None,
) -> Reward:
    """Edits name/description/cost_points (Issue #30). Extracted from the
    existing Web `PATCH /api/rewards/{id}` (routers/rewards.py), which
    already has exactly this behavior -- Adult-only, any Adult may edit any
    Reward (created_by is audit metadata, not ownership), partial update
    (a field left as None is left untouched, matching the existing
    RewardUpdate/PATCH semantics exactly -- this is also what lets a
    Telegram Edit flow's optional description step mean "keep the current
    value" for free).

    `created_by` and `created_at` are never touched. Every existing
    `RewardRedemption.cost_points` snapshot is immutable -- only future
    redemptions see a changed `cost_points`.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    try:
        payload = RewardUpdate(name=name, description=description, cost_points=cost_points)
    except ValidationError as exc:
        raise InvalidRewardInputError(_first_error_message(exc)) from exc

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
