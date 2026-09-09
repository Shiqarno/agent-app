import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    Task,
    TaskExecution,
    User,
    UserRole,
)
from app.reward_operations import get_available_balance, get_balance

# A page this small keeps each Telegram message short (Issue #27 "Page
# size") while still making pagination exercise-able in tests without huge
# fixtures.
PAGE_SIZE = 5

# Defensive fallback only -- adjust_points always requires a non-blank
# description, so a MANUAL_ADJUSTMENT row's description is never actually
# None in practice.
_MANUAL_ADJUSTMENT_FALLBACK_TEXT = "Points adjustment"


class PointsOperationError(Exception):
    """Base for every Points Application-layer failure (Issue #31).
    Framework-agnostic on purpose -- this module knows nothing about
    FastAPI or the Telegram bot library.
    """


class NotAuthorizedError(PointsOperationError):
    """The actor may not view or adjust this target User's Points (Issue
    #31 authorization matrix): self-view is always allowed for both roles;
    any cross-user access -- viewing or adjusting -- is Adult-acting-on-a-
    Child only. One check covers both read and write: an Adult adjusting a
    Child is never also a self-view case, so there is no overlap to
    special-case.
    """


class InvalidAdjustmentError(PointsOperationError):
    """amount/description failed validation. Carries a human-readable
    message (matching the RewardOperationError/UserOperationError
    convention) so the Telegram adapter can show exactly why.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InsufficientBalanceError(PointsOperationError):
    """A deduction would take the target User's *available* balance below
    zero (Issue #40: ledger balance minus their own active
    PENDING_CONFIRMATION reward requests -- see
    reward_operations.get_available_balance) -- not just the raw ledger
    balance. A manual removal must not spend points a pending Reward
    request already has frozen, for the same reason `redeem_reward` and
    `request_reward_redemption` check available balance rather than raw
    balance: they all draw from, and lock, the same User row.
    """


@dataclass(frozen=True)
class PointHistoryItem:
    """One ledger entry, already resolved to a human-readable description
    (Issue #27) -- Telegram (or any other adapter) renders this, but never
    sees the raw `PointTransactionReason` or which FK it came from.
    """

    amount: int
    description: str
    created_at: datetime


@dataclass(frozen=True)
class PointsView:
    """Adapter-neutral read model for the Points screen: balance and
    history read together so a caller never has to reconcile two
    independently-fetched values (see get_points).
    """

    balance: int
    transactions: list[PointHistoryItem]
    next_cursor: uuid.UUID | None


def _resolve_cursor_position(
    db: Session, user_id: uuid.UUID, cursor: uuid.UUID | None
) -> tuple[datetime, uuid.UUID] | None:
    """A cursor anchors pagination to (created_at, id) of the last item on
    the previous page (Issue #27 "Pagination"). Only the id travels in the
    Telegram callback (a full timestamp+id cursor would not fit in
    Telegram's 64-byte callback_data limit), so the anchor's created_at is
    re-resolved here from the id alone.

    Deliberately does not filter by `user_id`: the row is used only as a
    position marker for a WHERE clause that is *itself* always scoped to
    `user_id` below, so referencing another user's transaction id could at
    most jump this user's own pagination to a different point in their own
    timeline -- never leak another user's data (Issue #27 Authorization).
    A stale/unknown/invalid cursor simply falls back to the first page
    rather than erroring, since there is nothing sensitive to protect here.
    """
    if cursor is None:
        return None
    anchor = db.get(PointTransaction, cursor)
    if anchor is None:
        return None
    return anchor.created_at, anchor.id


def get_points(
    db: Session,
    actor: User,
    *,
    target_user: User | None = None,
    cursor: uuid.UUID | None = None,
) -> PointsView:
    """Balance plus one page of a User's own transaction history, newest
    first (Issue #27). Both are read via a single SQL statement (the
    balance as a correlated scalar subquery alongside each history row) so
    a concurrent redemption, task completion, or manual adjustment cannot
    produce a response where the displayed balance and the displayed
    history disagree -- exactly the inconsistency the spec calls out,
    without needing a non-default transaction isolation level.

    `target_user` defaults to `actor` (self-view, the pre-existing Issue
    #27 behavior). Passing a different `target_user` is an Adult viewing a
    Child's Points (Issue #31) -- one check covers the full authorization
    matrix: self-view is always allowed for both roles, and any other
    cross-user view requires the actor to be an Adult and the target to be
    a Child. Ownership of the *query* is enforced here, not by the caller:
    every row -- and the balance subquery -- is filtered by `target.id`,
    regardless of what a Telegram callback's cursor claims.
    """
    target = target_user if target_user is not None else actor
    is_cross_user = target.id != actor.id
    is_adult_viewing_child = actor.role == UserRole.ADULT and target.role == UserRole.CHILD
    if is_cross_user and not is_adult_viewing_child:
        raise NotAuthorizedError()

    position = _resolve_cursor_position(db, target.id, cursor)

    balance_subquery = (
        select(func.coalesce(func.sum(PointTransaction.amount), 0))
        .where(PointTransaction.user_id == target.id)
        .scalar_subquery()
    )
    stmt = (
        select(PointTransaction, Task.title, Reward.name, balance_subquery)
        .outerjoin(TaskExecution, TaskExecution.id == PointTransaction.task_execution_id)
        .outerjoin(Task, Task.id == TaskExecution.task_id)
        .outerjoin(RewardRedemption, RewardRedemption.id == PointTransaction.redemption_id)
        .outerjoin(Reward, Reward.id == RewardRedemption.reward_id)
        .where(PointTransaction.user_id == target.id)
    )
    if position is not None:
        stmt = stmt.where(tuple_(PointTransaction.created_at, PointTransaction.id) < position)
    stmt = stmt.order_by(PointTransaction.created_at.desc(), PointTransaction.id.desc()).limit(
        PAGE_SIZE + 1
    )

    rows = db.execute(stmt).all()

    if not rows:
        # No rows to carry the balance subquery -- the ledger is either
        # genuinely empty or this cursor is past the last page.
        balance = db.scalar(
            select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
                PointTransaction.user_id == target.id
            )
        )
        assert balance is not None  # COALESCE guarantees a non-null row
        return PointsView(balance=balance, transactions=[], next_cursor=None)

    balance = rows[0][3]
    has_next_page = len(rows) > PAGE_SIZE
    page_rows = rows[:PAGE_SIZE]

    transactions = [
        PointHistoryItem(
            amount=transaction.amount,
            description=_describe_transaction(transaction, task_title, reward_name),
            created_at=transaction.created_at,
        )
        for transaction, task_title, reward_name, _ in page_rows
    ]
    next_cursor = page_rows[-1][0].id if has_next_page else None

    return PointsView(balance=balance, transactions=transactions, next_cursor=next_cursor)


def _describe_transaction(
    transaction: PointTransaction, task_title: str | None, reward_name: str | None
) -> str:
    """Human-readable source, never the raw `PointTransactionReason`
    (Issue #27): the Task title for a completion, the Reward name for a
    redemption, and -- new in Issue #31 -- the Adult-provided description
    for a manual adjustment, which has neither join match.
    """
    if task_title is not None:
        return task_title
    if reward_name is not None:
        return reward_name
    return transaction.description or _MANUAL_ADJUSTMENT_FALLBACK_TEXT


def adjust_points(
    db: Session, actor: User, target_user: User, *, amount: int, description: str
) -> tuple[PointTransaction, int]:
    """Manually adds or removes Points for a Child (Issue #31) -- an
    ordinary immutable `PointTransaction` with `reason=MANUAL_ADJUSTMENT`,
    never a mutable balance field. Adult-only, Child-target-only,
    Application-layer authorization (not just a Telegram-UI restriction).

    Concurrency mirrors `reward_operations.redeem_reward`'s established
    pattern exactly: locks the target User row for the duration of the
    transaction, so the balance check and the write are atomic with
    respect to any other adjustment, redemption, or Reward
    request/confirmation by this same User -- coexisting safely with, and
    not weakening, any of their existing guarantees (all lock the same
    User row).

    The balance check (Issue #40) is against *available* balance, not raw
    ledger balance: a Child's pending Reward requests already have their
    cost frozen against that same balance, and a manual removal must not
    be allowed to spend points a not-yet-decided request is holding, or a
    later Adult confirmation of that request could push the ledger
    negative. See `reward_operations.get_available_balance`.
    """
    if actor.role != UserRole.ADULT or target_user.role != UserRole.CHILD:
        raise NotAuthorizedError()

    if amount == 0:
        raise InvalidAdjustmentError("Amount must not be zero.")

    normalized_description = description.strip()
    if not normalized_description:
        raise InvalidAdjustmentError("Please enter a description.")

    # A plain SELECT ... FOR UPDATE (not Session.get, which may
    # short-circuit via the identity map) guarantees a real round-trip that
    # acquires the row lock.
    db.execute(select(User).where(User.id == target_user.id).with_for_update()).scalar_one()

    available_balance = get_available_balance(db, target_user.id)
    if available_balance + amount < 0:
        raise InsufficientBalanceError()

    balance = get_balance(db, target_user.id)
    new_balance = balance + amount

    transaction = PointTransaction(
        user_id=target_user.id,
        amount=amount,
        reason=PointTransactionReason.MANUAL_ADJUSTMENT,
        description=normalized_description,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return transaction, new_balance
