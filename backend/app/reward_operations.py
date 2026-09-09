import uuid

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    RewardRedemptionStatus,
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
    """The User's current *available* balance (ledger balance minus the sum
    of their own active PENDING_CONFIRMATION reward requests -- Issue #39)
    is less than the Reward's current cost. Also raised by the legacy
    `redeem_reward` immediate-redemption path, which has no requests of its
    own to freeze against, so its available balance is simply the ledger
    balance.
    """


class NotAnAdultError(RewardOperationError):
    """Only an Adult may manage the Reward catalog (create/update), or
    confirm/reject a pending Reward request (Issue #39).
    """


class RewardRedemptionNotActionableError(RewardOperationError):
    """No PENDING_CONFIRMATION RewardRedemption exists with this id --
    missing, or already CONFIRMED/REJECTED (Issue #39). Terminal states are
    immutable: this is raised identically whether the id never existed or
    the request has already been resolved, so a stale/duplicate
    Confirm/Return can never act twice.
    """


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


def _frozen_amount(db: Session, user_id: uuid.UUID) -> int:
    """The sum of `cost_points` across this User's own currently
    PENDING_CONFIRMATION reward requests (Issue #39) -- points reserved
    against a decision an Adult hasn't made yet, never a ledger entry.
    """
    frozen = db.scalar(
        select(func.coalesce(func.sum(RewardRedemption.cost_points), 0)).where(
            RewardRedemption.user_id == user_id,
            RewardRedemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION,
        )
    )
    assert frozen is not None  # COALESCE guarantees a non-null row
    return frozen


def get_available_balance(db: Session, user_id: uuid.UUID) -> int:
    """Ledger balance minus this User's own active frozen reward requests
    (Issue #39) -- what they can actually still request right now. The
    Point Ledger itself remains the sole source of truth for points
    actually earned/spent; frozen amounts never touch it and this function
    never mutates anything, it only computes a read-time projection.
    """
    return get_balance(db, user_id) - _frozen_amount(db, user_id)


def get_rewards(db: Session, user: User) -> tuple[list[Reward], int]:
    """The global Reward catalog, plus the current User's *available*
    balance (Issue #39: ledger balance minus their own active frozen
    reward requests) so a caller can render affordability without a second
    round trip (Issue #26 section "Rewards list"). Not scoped by role or
    ownership -- every User sees the same catalog, exactly like the
    existing Web `GET /api/rewards`.
    """
    rewards = list(db.scalars(select(Reward).order_by(Reward.name.asc(), Reward.id.asc())))
    return rewards, get_available_balance(db, user.id)


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

    Checks *available* balance (Issue #39: ledger balance minus this
    User's own active PENDING_CONFIRMATION reward requests), not raw
    ledger balance -- this immediate path and the Telegram request/confirm
    flow draw from the same balance and hold the same User row lock, so an
    immediate redemption here must not spend points a not-yet-decided
    Telegram request already has frozen, or a later Adult confirmation of
    that request could push the ledger negative. For a User with no active
    frozen requests (every pre-Issue-#39 User, and every User who has never
    used the Telegram request flow), available balance and ledger balance
    are identical, so this is behavior-preserving for the existing,
    already-tested contract in every case that could previously occur.
    """
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    # A plain SELECT ... FOR UPDATE (not Session.get, which may
    # short-circuit via the identity map) guarantees a real round-trip that
    # acquires the row lock.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()

    balance = get_available_balance(db, user.id)
    if balance < reward.cost_points:
        raise InsufficientPointsError()

    redemption_id = uuid.uuid4()
    redemption = RewardRedemption(
        id=redemption_id,
        reward_id=reward.id,
        user_id=user.id,
        cost_points=reward.cost_points,
        status=RewardRedemptionStatus.CONFIRMED,
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


def request_reward_redemption(
    db: Session, user: User, reward_id: uuid.UUID
) -> tuple[RewardRedemption, Reward, int]:
    """Creates a PENDING_CONFIRMATION request for a Reward at its CURRENT
    cost (Issue #39) -- the Telegram Child Rewards workflow's entry point,
    replacing what used to be an immediate `redeem_reward` call there.
    Freezes `cost_points` against the requester's available balance; never
    creates a PointTransaction and never touches the Point Ledger -- that
    only happens if/when an Adult later confirms it
    (`confirm_reward_redemption`).

    Deliberately no Child-only check here, mirroring `redeem_reward`
    exactly (see its docstring): "Adult doesn't get a Get/Request action"
    is a Telegram UX decision, not an Application-layer rule.

    Concurrency: same pattern as `redeem_reward` -- locks the User row for
    the duration of the transaction, so the available-balance check and
    the write are atomic with respect to any other request or immediate
    redemption by this same User. Two concurrent requests that would
    together overspend the available balance cannot both pass the check:
    whichever acquires the row lock first commits its freeze, and the
    other re-reads the now-lower available balance and is cleanly
    rejected. No new locking infrastructure -- the same row lock already
    protects every other balance-mutating operation on this User.
    """
    reward = db.get(Reward, reward_id)
    if reward is None:
        raise RewardNotFoundError()

    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()

    available = get_available_balance(db, user.id)
    if available < reward.cost_points:
        raise InsufficientPointsError()

    redemption = RewardRedemption(
        reward_id=reward.id,
        user_id=user.id,
        cost_points=reward.cost_points,
        status=RewardRedemptionStatus.PENDING_CONFIRMATION,
    )
    db.add(redemption)
    db.commit()
    db.refresh(redemption)

    return redemption, reward, available - reward.cost_points


def _get_redemption_for_update(db: Session, redemption_id: uuid.UUID) -> RewardRedemption | None:
    """Loads a RewardRedemption with its row lock held for the rest of the
    transaction (Issue #39) -- same rationale as
    task_operations._get_execution_for_update: confirm/reject reads
    `status` then decides whether to act, so this must serialize against a
    concurrent confirm/reject of the same request.
    """
    stmt = select(RewardRedemption).where(RewardRedemption.id == redemption_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_pending_reward_requests(
    db: Session, user: User
) -> list[tuple[RewardRedemption, Reward, User]]:
    """Reward requests currently PENDING_CONFIRMATION (Issue #39), paired
    with their Reward and requesting Child for presentation -- the Reward
    analogue of task_operations.get_pending_confirmations, feeding the same
    Adult /confirmations surface. Deliberately no ownership filter, for the
    same reason as that function: any Adult sees every pending request, not
    just ones for Rewards they created.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    stmt = (
        select(RewardRedemption, Reward, User)
        .join(Reward, Reward.id == RewardRedemption.reward_id)
        .join(User, User.id == RewardRedemption.user_id)
        .where(RewardRedemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION)
        .order_by(RewardRedemption.created_at.asc())
    )
    return [(redemption, reward, child) for redemption, reward, child in db.execute(stmt).all()]


def confirm_reward_redemption(
    db: Session, actor: User, redemption_id: uuid.UUID
) -> tuple[RewardRedemption, Reward, User]:
    """PENDING_CONFIRMATION -> CONFIRMED, plus exactly one REWARD_REDEEMED
    PointTransaction, atomically (Issue #39/#40) -- the Reward analogue of
    task_operations.confirm_execution. Releasing the freeze is implicit:
    once `status` is no longer PENDING_CONFIRMATION, `_frozen_amount` no
    longer counts this redemption, and the real ledger deduction below
    takes its place.

    Authorization is role-only, matching confirm_execution: any Adult may
    confirm any pending request, no Adult<->Child ownership.

    Concurrency (Issue #40): unlike TASK_COMPLETED (always a positive
    ledger entry, so it can never push the balance negative and never
    needed this), a REWARD_REDEEMED entry is a real deduction -- exactly
    the kind of change `request_reward_redemption`, `redeem_reward`, and
    `adjust_points` all serialize against each other for by locking the
    User row first. This must join that same serialization, or a manual
    adjustment racing (or having already landed) between the request and
    this confirmation could leave the ledger unable to absorb the
    deduction. Lock order is User row, then the RewardRedemption row
    (matching the pipeline this Issue specifies) -- the *only* place this
    module ever holds two locks at once, so establishing "User first" here
    (the same row every other point-mutating operation on this User locks
    first, and the only row `request_reward_redemption`/`redeem_reward`/
    `adjust_points` ever lock) introduces no new deadlock risk: nothing
    else in this module locks a RewardRedemption row while also wanting a
    User row in the other order (`reject_reward_redemption` only ever
    locks the RewardRedemption row, never User).

    The User id to lock is read from an unlocked, preliminary lookup --
    safe because `user_id` on a RewardRedemption is set once at creation
    and never changes; only `status` is ever mutated, and that is
    re-validated below only *after* both locks are held.

    If the ledger can no longer actually absorb this deduction (e.g. a
    manual adjustment landed in between that ignored -- or, pre-Issue-#40,
    could ignore -- this freeze), confirmation fails with
    InsufficientPointsError rather than creating a negative balance, a
    partial redemption, or silently reducing the frozen amount. The
    request is left exactly as PENDING_CONFIRMATION -- still actionable,
    so an Adult can Return it, or retry Confirm once the Child's balance
    recovers -- never silently advanced to a terminal state without its
    transaction.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    redemption_lookup = db.get(RewardRedemption, redemption_id)
    if redemption_lookup is None:
        raise RewardRedemptionNotActionableError()

    db.execute(
        select(User).where(User.id == redemption_lookup.user_id).with_for_update()
    ).scalar_one()

    redemption = _get_redemption_for_update(db, redemption_id)
    if redemption is None or redemption.status != RewardRedemptionStatus.PENDING_CONFIRMATION:
        raise RewardRedemptionNotActionableError()

    if get_balance(db, redemption.user_id) < redemption.cost_points:
        raise InsufficientPointsError()

    redemption.status = RewardRedemptionStatus.CONFIRMED
    db.add(
        PointTransaction(
            user_id=redemption.user_id,
            redemption_id=redemption.id,
            amount=-redemption.cost_points,
            reason=PointTransactionReason.REWARD_REDEEMED,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RewardRedemptionNotActionableError() from exc
    db.refresh(redemption)

    reward = db.get(Reward, redemption.reward_id)
    assert reward is not None  # a RewardRedemption's Reward is never deleted
    child = db.get(User, redemption.user_id)
    assert child is not None
    return redemption, reward, child


def reject_reward_redemption(
    db: Session, actor: User, redemption_id: uuid.UUID
) -> tuple[RewardRedemption, Reward, User]:
    """PENDING_CONFIRMATION -> REJECTED (Issue #39) -- the Reward analogue
    of task_operations.return_execution_to_work. Never creates a
    PointTransaction; releasing the freeze is the same implicit effect of
    leaving PENDING_CONFIRMATION as confirm_reward_redemption's, just
    without a ledger entry to replace it.

    Deliberately does not lock the User row (Issue #40, unlike
    confirm_reward_redemption): this never reads or checks a balance and
    never writes a PointTransaction, so there is nothing here that needs
    serializing against `adjust_points`/`redeem_reward`/
    `request_reward_redemption` -- the RewardRedemption row's own lock is
    sufficient to make the status transition itself safe.
    """
    if actor.role != UserRole.ADULT:
        raise NotAnAdultError()

    redemption = _get_redemption_for_update(db, redemption_id)
    if redemption is None or redemption.status != RewardRedemptionStatus.PENDING_CONFIRMATION:
        raise RewardRedemptionNotActionableError()

    redemption.status = RewardRedemptionStatus.REJECTED
    db.commit()
    db.refresh(redemption)

    reward = db.get(Reward, redemption.reward_id)
    assert reward is not None
    child = db.get(User, redemption.user_id)
    assert child is not None
    return redemption, reward, child


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
