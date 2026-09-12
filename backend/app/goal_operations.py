import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import (
    Goal,
    GoalContribution,
    GoalStatus,
    PointTransaction,
    PointTransactionReason,
    User,
    UserRole,
    utcnow,
)
from app.reward_operations import get_available_balance
from app.schemas import GoalCreate, GoalUpdate

# Same rationale as points_operations.PAGE_SIZE (Issue #27): keeps each
# Telegram message short while still making pagination exercise-able in
# tests without huge fixtures.
PAGE_SIZE = 5


class GoalOperationError(Exception):
    """Base for every Goal Application-layer failure (Issue: Goals).
    Framework-agnostic on purpose -- this module knows nothing about
    FastAPI or the Telegram bot library; each adapter that calls it is
    responsible for translating these into its own presentation.
    """


class NotAnAdultError(GoalOperationError):
    """Only an Adult may create or edit a Goal."""


class NotAChildError(GoalOperationError):
    """Only a Child may contribute their own points to a Goal."""


class GoalNotFoundError(GoalOperationError):
    """No Goal exists with this id."""


class GoalNotEditableError(GoalOperationError):
    """The Goal is COMPLETED, so its name/cost can no longer be edited --
    also what keeps a completed Goal from ever being turned back into an
    active one: update_goal refuses to touch a COMPLETED row at all,
    before looking at any of the requested field changes, and there is no
    field on GoalUpdate that could set `status` directly.
    """


class InvalidGoalInputError(GoalOperationError):
    """name/cost_points failed validation. Carries a human-readable
    message (reusing the existing GoalCreate/GoalUpdate Pydantic
    validation, matching the TaskCreate/RewardCreate convention) so the
    Telegram adapter can show exactly why, without re-deriving the rules.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GoalNotActiveError(GoalOperationError):
    """The Goal is COMPLETED, so it can no longer receive contributions."""


class InvalidContributionAmountError(GoalOperationError):
    """The requested transfer amount was not a positive integer."""


class InsufficientPointsError(GoalOperationError):
    """The Child's *available* balance (ledger balance minus their own
    active PENDING_CONFIRMATION reward requests -- see
    reward_operations.get_available_balance) is less than the requested
    transfer. A Goal contribution draws from, and locks, the same User row
    every other balance-mutating operation does, so it must not be allowed
    to spend points a pending Reward request already has frozen.
    """


class ContributionExceedsRemainingAmountError(GoalOperationError):
    """The requested transfer would push `accumulated_points` past
    `cost_points` -- this Issue does not allow overfunding a Goal.
    """


def _first_error_message(exc: ValidationError) -> str:
    message: str = exc.errors()[0]["msg"]
    # Pydantic prefixes a field_validator's own ValueError with "Value
    # error, "; the Field(gt=0) constraint message doesn't have that
    # prefix. Strip it so Telegram never shows the internal wrapper text.
    return message.removeprefix("Value error, ")


def _get_goal_for_update(db: Session, goal_id: uuid.UUID) -> Goal | None:
    """Loads a Goal with its row lock held for the rest of the transaction
    -- same rationale as task_operations._get_execution_for_update /
    reward_operations._get_redemption_for_update: both update_goal and
    contribute_to_goal read `status` (and, for contribute_to_goal,
    `accumulated_points`/`cost_points`) then decide whether to act, so
    this must serialize against a concurrent edit or contribution to the
    same Goal.
    """
    stmt = select(Goal).where(Goal.id == goal_id).with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_active_goals(db: Session, user: User) -> list[Goal]:
    """Every currently-ACTIVE Goal (Issue: Goals), newest first -- the
    Child `/goals` list: only Goals still open for contribution, matching
    `/tasks`'s own "only what you can currently act on" convention.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()

    stmt = (
        select(Goal).where(Goal.status == GoalStatus.ACTIVE).order_by(Goal.created_at.asc())
    )
    return list(db.scalars(stmt))


def get_goals(db: Session, user: User) -> list[Goal]:
    """The full Goal catalog -- active and completed -- for Adult
    management (Issue: Goals), matching task_operations.get_tasks /
    reward catalog management's "see everything, not just what's
    currently actionable" shape.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    return list(db.scalars(select(Goal).order_by(Goal.created_at.asc())))


def create_goal(db: Session, user: User, *, name: str, cost_points: int) -> Goal:
    """Creates a new Goal, ACTIVE immediately with zero accumulated points
    (Issue: Goals). Reuses the existing GoalCreate Pydantic validation
    (name non-blank, cost_points > 0), matching create_task/create_reward.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    try:
        payload = GoalCreate(name=name, cost_points=cost_points)
    except ValidationError as exc:
        raise InvalidGoalInputError(_first_error_message(exc)) from exc

    goal = Goal(
        name=payload.name,
        cost_points=payload.cost_points,
        accumulated_points=0,
        status=GoalStatus.ACTIVE,
        created_by=user.id,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(
    db: Session,
    user: User,
    goal_id: uuid.UUID,
    *,
    name: str | None = None,
    cost_points: int | None = None,
) -> Goal:
    """Edits name/cost_points on an ACTIVE Goal (Issue: Goals) -- refused
    outright once COMPLETED, before validating or applying any field
    change, which is also what makes a COMPLETED Goal impossible to turn
    back into an ACTIVE one (there is no `status` field to set here at all).

    After applying the change, immediately re-evaluates
    `accumulated_points >= cost_points`: lowering the cost to (or below)
    the already-accumulated amount completes the Goal in the same
    transaction, exactly like reaching the target via a contribution does
    -- an active Goal must never be left active once its own accumulated
    balance already satisfies its cost.

    Concurrency: holds the same Goal row lock contribute_to_goal takes
    (via _get_goal_for_update), so a concurrent edit and contribution to
    the same Goal fully serialize.
    """
    if user.role != UserRole.ADULT:
        raise NotAnAdultError()

    goal = _get_goal_for_update(db, goal_id)
    if goal is None:
        raise GoalNotFoundError()
    if goal.status != GoalStatus.ACTIVE:
        raise GoalNotEditableError()

    try:
        payload = GoalUpdate(name=name, cost_points=cost_points)
    except ValidationError as exc:
        raise InvalidGoalInputError(_first_error_message(exc)) from exc

    if payload.name is not None:
        goal.name = payload.name
    if payload.cost_points is not None:
        goal.cost_points = payload.cost_points

    if goal.accumulated_points >= goal.cost_points:
        goal.status = GoalStatus.COMPLETED

    goal.updated_at = utcnow()
    db.commit()
    db.refresh(goal)
    return goal


def contribute_to_goal(
    db: Session, user: User, goal_id: uuid.UUID, amount: int
) -> tuple[GoalContribution, Goal, int]:
    """Atomically transfers `amount` points from the Child's own ledger
    balance into an ACTIVE Goal's accumulated balance (Issue: Goals) --
    the Goal analogue of reward_operations.request_reward_redemption, but
    a single immediate step rather than a two-step request/confirm flow:
    the ledger deduction happens right here, not later.

    Concurrency: locks the Child's own User row first (the same row every
    other balance-mutating operation on this User locks first --
    redeem_reward, request_reward_redemption, adjust_points,
    confirm_reward_redemption -- so this join theirs without introducing a
    new deadlock ordering), then the Goal row (_get_goal_for_update).
    Locking the Child first serializes two concurrent contributions by the
    *same* Child (whichever acquires the row lock first re-reads and
    spends the current balance; the second sees the now-lower balance).
    Locking the Goal second serializes two *different* Children
    contributing to the *same* Goal: whichever transaction reaches the
    Goal lock first commits its contribution and (if it completes the
    Goal) its COMPLETED status; the other re-reads the now-current
    accumulated_points/status under its own lock and is rejected --
    GoalNotActiveError if the Goal is now COMPLETED,
    ContributionExceedsRemainingAmountError if it's still ACTIVE but no
    longer has room for this amount -- before mutating anything. This is
    also exactly what prevents overfunding: the remaining-amount check
    always runs against a freshly locked, current `accumulated_points`.
    """
    if user.role != UserRole.CHILD:
        raise NotAChildError()
    if amount <= 0:
        raise InvalidContributionAmountError()

    # A plain SELECT ... FOR UPDATE (not Session.get, which may
    # short-circuit via the identity map) guarantees a real round-trip
    # that acquires the row lock -- same pattern as every other
    # balance-mutating operation in this project.
    db.execute(select(User).where(User.id == user.id).with_for_update()).scalar_one()

    goal = _get_goal_for_update(db, goal_id)
    if goal is None:
        raise GoalNotFoundError()
    if goal.status != GoalStatus.ACTIVE:
        raise GoalNotActiveError()

    remaining = goal.cost_points - goal.accumulated_points
    if amount > remaining:
        raise ContributionExceedsRemainingAmountError()

    available_balance = get_available_balance(db, user.id)
    if amount > available_balance:
        raise InsufficientPointsError()

    contribution = GoalContribution(goal_id=goal.id, user_id=user.id, amount=amount)
    db.add(contribution)
    # Flush (not commit) so the contribution row exists before the
    # FK-referencing PointTransaction insert below; both statements still
    # land in the same open transaction and commit together.
    db.flush()

    db.add(
        PointTransaction(
            user_id=user.id,
            goal_contribution_id=contribution.id,
            amount=-amount,
            reason=PointTransactionReason.GOAL_CONTRIBUTION,
        )
    )

    goal.accumulated_points += amount
    if goal.accumulated_points >= goal.cost_points:
        goal.status = GoalStatus.COMPLETED
    goal.updated_at = utcnow()

    db.commit()
    db.refresh(contribution)
    db.refresh(goal)

    return contribution, goal, available_balance - amount


@dataclass(frozen=True)
class GoalContributionItem:
    """One contribution, already resolved to its contributing Child's name
    (Issue: Goals) -- Telegram (or any other adapter) renders this without
    a second join of its own.
    """

    amount: int
    child_name: str
    created_at: datetime


@dataclass(frozen=True)
class GoalDetailsView:
    """Adapter-neutral read model for the Goal Details screen: the Goal
    itself plus one page of its contribution history, read together so a
    caller never has to reconcile two independently-fetched values --
    same rationale as points_operations.PointsView.
    """

    goal: Goal
    contributions: list[GoalContributionItem]
    next_cursor: uuid.UUID | None


def _resolve_contribution_cursor_position(
    db: Session, cursor: uuid.UUID | None
) -> tuple[datetime, uuid.UUID] | None:
    """Same rationale as points_operations._resolve_cursor_position: only
    the contribution id travels in the Telegram callback, so the anchor's
    created_at is re-resolved here from the id alone. Deliberately does
    not filter by goal_id -- the row is only a position marker for a WHERE
    clause that is itself always scoped to goal_id in get_goal_details
    below, so a stale/foreign id could at most jump this Goal's own
    pagination to a different point in its own timeline, never leak
    another Goal's contributions.
    """
    if cursor is None:
        return None
    anchor = db.get(GoalContribution, cursor)
    if anchor is None:
        return None
    return anchor.created_at, anchor.id


def get_goal_details(
    db: Session, goal_id: uuid.UUID, cursor: uuid.UUID | None = None
) -> GoalDetailsView:
    """The Goal itself plus one page of its contribution history, newest
    first (Issue: Goals) -- used by both the Adult and the Child Goal
    Details screens; viewing a Goal has no role restriction (Goals are
    global, like Rewards), so this takes no actor. Raises GoalNotFoundError
    if the Goal doesn't exist -- callers never need a separate existence
    check of their own.
    """
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise GoalNotFoundError()

    position = _resolve_contribution_cursor_position(db, cursor)

    stmt = (
        select(GoalContribution, User.name)
        .join(User, User.id == GoalContribution.user_id)
        .where(GoalContribution.goal_id == goal_id)
    )
    if position is not None:
        stmt = stmt.where(tuple_(GoalContribution.created_at, GoalContribution.id) < position)
    stmt = stmt.order_by(
        GoalContribution.created_at.desc(), GoalContribution.id.desc()
    ).limit(PAGE_SIZE + 1)

    rows = db.execute(stmt).all()
    has_next_page = len(rows) > PAGE_SIZE
    page_rows = rows[:PAGE_SIZE]

    contributions = [
        GoalContributionItem(
            amount=contribution.amount, child_name=name, created_at=contribution.created_at
        )
        for contribution, name in page_rows
    ]
    next_cursor = page_rows[-1][0].id if has_next_page else None

    return GoalDetailsView(goal=goal, contributions=contributions, next_cursor=next_cursor)
