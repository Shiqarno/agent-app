import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    Reward,
    RewardRedemption,
    Task,
    TaskExecution,
    User,
)

# A page this small keeps each Telegram message short (Issue #27 "Page
# size") while still making pagination exercise-able in tests without huge
# fixtures.
PAGE_SIZE = 5


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


def get_points(db: Session, user: User, *, cursor: uuid.UUID | None = None) -> PointsView:
    """Balance plus one page of the User's own transaction history, newest
    first (Issue #27). Both are read via a single SQL statement (the
    balance as a correlated scalar subquery alongside each history row) so
    a concurrent redemption or task completion cannot produce a response
    where the displayed balance and the displayed history disagree --
    exactly the inconsistency the spec calls out, without needing a
    non-default transaction isolation level.

    Ownership is enforced here, not by the caller: every row -- and the
    balance subquery -- is filtered by `user.id`, regardless of what a
    Telegram callback's cursor claims.
    """
    position = _resolve_cursor_position(db, user.id, cursor)

    balance_subquery = (
        select(func.coalesce(func.sum(PointTransaction.amount), 0))
        .where(PointTransaction.user_id == user.id)
        .scalar_subquery()
    )
    stmt = (
        select(PointTransaction, Task.title, Reward.name, balance_subquery)
        .outerjoin(TaskExecution, TaskExecution.id == PointTransaction.task_execution_id)
        .outerjoin(Task, Task.id == TaskExecution.task_id)
        .outerjoin(RewardRedemption, RewardRedemption.id == PointTransaction.redemption_id)
        .outerjoin(Reward, Reward.id == RewardRedemption.reward_id)
        .where(PointTransaction.user_id == user.id)
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
                PointTransaction.user_id == user.id
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
            description=task_title if task_title is not None else reward_name,
            created_at=transaction.created_at,
        )
        for transaction, task_title, reward_name, _ in page_rows
    ]
    next_cursor = page_rows[-1][0].id if has_next_page else None

    return PointsView(balance=balance, transactions=transactions, next_cursor=next_cursor)
