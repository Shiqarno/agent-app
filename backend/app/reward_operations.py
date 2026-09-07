import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PointTransaction, PointTransactionReason, Reward, RewardRedemption, User


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
