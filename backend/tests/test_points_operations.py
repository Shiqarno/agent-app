import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)
from app.points_operations import PAGE_SIZE, get_points

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_task_completed(
    db_session: Session,
    user: User,
    amount: int,
    *,
    title: str = "Seed task",
    created_at: datetime | None = None,
) -> PointTransaction:
    task = Task(title=title, reward_points=amount, created_by=user.id)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id, user_id=user.id, status=TaskExecutionStatus.COMPLETED, reward_points=amount
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    txn = PointTransaction(
        user_id=user.id,
        task_execution_id=execution.id,
        amount=amount,
        reason=PointTransactionReason.TASK_COMPLETED,
    )
    if created_at is not None:
        txn.created_at = created_at
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)
    return txn


def _make_reward_redeemed(
    db_session: Session,
    user: User,
    amount: int,
    *,
    name: str = "Seed reward",
    created_at: datetime | None = None,
) -> PointTransaction:
    reward = Reward(name=name, cost_points=abs(amount), created_by=user.id)
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)

    redemption = RewardRedemption(reward_id=reward.id, user_id=user.id, cost_points=abs(amount))
    db_session.add(redemption)
    db_session.commit()
    db_session.refresh(redemption)

    txn = PointTransaction(
        user_id=user.id,
        redemption_id=redemption.id,
        amount=amount,
        reason=PointTransactionReason.REWARD_REDEEMED,
    )
    if created_at is not None:
        txn.created_at = created_at
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)
    return txn


# =========================================================================================
# Balance
# =========================================================================================


def test_balance_is_correct(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)
    _make_reward_redeemed(db_session, child, -40)

    view = get_points(db_session, child)

    assert view.balance == 60


def test_no_mutable_balance_column_is_used(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """The balance always reflects the ledger, not a stored field -- there
    is no User.points_balance to accidentally read instead.
    """
    assert not hasattr(User, "points_balance")


# =========================================================================================
# Ownership
# =========================================================================================


def test_child_receives_only_their_own_transactions(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    other = make_user(CHILD, "Other Child")
    mine = _make_task_completed(db_session, child, 20, title="Mine")
    _make_task_completed(db_session, other, 30, title="Not mine")

    view = get_points(db_session, child)

    assert len(view.transactions) == 1
    assert view.transactions[0].description == "Mine"
    assert view.transactions[0].amount == mine.amount


def test_another_users_balance_is_not_included(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    other = make_user(CHILD, "Other Child")
    _make_task_completed(db_session, other, 1000)

    view = get_points(db_session, child)

    assert view.balance == 0


# =========================================================================================
# History
# =========================================================================================


def test_history_is_returned_newest_first(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    earliest = _make_task_completed(
        db_session, child, 10, title="Earliest", created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    latest = _make_task_completed(
        db_session, child, 20, title="Latest", created_at=datetime(2026, 1, 3, tzinfo=UTC)
    )

    view = get_points(db_session, child)

    assert [item.description for item in view.transactions] == ["Latest", "Earliest"]
    assert view.transactions[0].amount == latest.amount
    assert view.transactions[1].amount == earliest.amount


def test_identical_timestamps_use_id_as_a_deterministic_tiebreaker(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    same_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    first = _make_task_completed(db_session, child, 10, title="First", created_at=same_time)
    second = _make_task_completed(db_session, child, 20, title="Second", created_at=same_time)
    expected_order = sorted([first.id, second.id], reverse=True)

    view = get_points(db_session, child)

    expected_descriptions = ["First" if i == first.id else "Second" for i in expected_order]
    assert [item.description for item in view.transactions] == expected_descriptions

    # Calling again must produce the exact same order -- determinism, not luck.
    view_again = get_points(db_session, child)
    assert [item.description for item in view_again.transactions] == expected_descriptions


def test_task_completed_shows_the_task_title(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 20, title="Clean room")

    view = get_points(db_session, child)

    assert view.transactions[0].description == "Clean room"
    assert view.transactions[0].amount == 20


def test_reward_redeemed_shows_the_reward_name(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)
    _make_reward_redeemed(db_session, child, -100, name="Ice cream")

    view = get_points(db_session, child)

    redeemed = next(item for item in view.transactions if item.amount < 0)
    assert redeemed.description == "Ice cream"
    assert redeemed.amount == -100


def test_technical_reason_is_not_exposed(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 20, title="Clean room")

    view = get_points(db_session, child)

    assert not hasattr(view.transactions[0], "reason")
    assert "TASK_COMPLETED" not in view.transactions[0].description


def test_signed_amounts_are_preserved(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)
    _make_reward_redeemed(db_session, child, -40)

    view = get_points(db_session, child)

    amounts = sorted(item.amount for item in view.transactions)
    assert amounts == [-40, 100]


# =========================================================================================
# Empty state
# =========================================================================================


def test_user_with_no_transactions_has_empty_history(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)

    view = get_points(db_session, child)

    assert view.transactions == []
    assert view.balance == 0
    assert view.next_cursor is None


def test_zero_balance_with_existing_history_still_shows_history(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 20, title="Clean room")
    _make_reward_redeemed(db_session, child, -20, name="Ice cream")

    view = get_points(db_session, child)

    assert view.balance == 0
    assert len(view.transactions) == 2


# =========================================================================================
# Pagination
# =========================================================================================


def _seed_n_transactions(db_session: Session, user: User, count: int) -> list[PointTransaction]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        _make_task_completed(
            db_session,
            user,
            index,
            title=f"Task {index}",
            created_at=base.replace(day=index + 1),
        )
        for index in range(count)
    ]


def test_first_page_returns_only_the_page_size(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _seed_n_transactions(db_session, child, PAGE_SIZE + 3)

    view = get_points(db_session, child)

    assert len(view.transactions) == PAGE_SIZE


def test_next_cursor_present_when_more_records_exist(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _seed_n_transactions(db_session, child, PAGE_SIZE + 1)

    view = get_points(db_session, child)

    assert view.next_cursor is not None


def test_final_page_has_no_next_cursor(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    _seed_n_transactions(db_session, child, PAGE_SIZE)

    view = get_points(db_session, child)

    assert view.next_cursor is None


def test_next_page_starts_after_the_previous_page_with_no_gaps_or_duplicates(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    transactions = _seed_n_transactions(db_session, child, PAGE_SIZE * 2 + 2)

    first_page = get_points(db_session, child)
    assert first_page.next_cursor is not None
    second_page = get_points(db_session, child, cursor=first_page.next_cursor)
    assert second_page.next_cursor is not None
    third_page = get_points(db_session, child, cursor=second_page.next_cursor)

    all_amounts = [
        item.amount for page in (first_page, second_page, third_page) for item in page.transactions
    ]
    # Descriptions double as an identity check here ("Task {index}"),
    # amount == index by construction of _seed_n_transactions.
    seen_indices = [
        int(item.description.removeprefix("Task "))
        for page in (first_page, second_page, third_page)
        for item in page.transactions
    ]
    expected_indices = list(range(len(transactions) - 1, -1, -1))
    assert seen_indices == expected_indices
    assert len(set(seen_indices)) == len(seen_indices)  # no duplicates
    assert len(all_amounts) == len(transactions)  # no skipped records
    assert third_page.next_cursor is None


def test_unknown_cursor_falls_back_to_the_first_page(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _seed_n_transactions(db_session, child, PAGE_SIZE)

    view = get_points(db_session, child, cursor=uuid.uuid4())

    assert len(view.transactions) == PAGE_SIZE


# =========================================================================================
# Consistent read
# =========================================================================================


def test_balance_and_history_are_read_from_the_same_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """The balance returned alongside a page of history must reflect
    exactly the transactions summed in that same read -- not a separately
    fetched value that could reflect a different point in time.
    """
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 20)
    _make_reward_redeemed(db_session, child, -20)

    view = get_points(db_session, child)

    assert view.balance == sum(item.amount for item in view.transactions)


def test_get_points_reads_balance_and_history_in_a_single_query(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Balance and history must come from ONE database round trip, not two
    independently-issued queries that could each observe a different
    commit of a concurrent redemption/completion landing in between (Issue
    #27 "Balance + history consistency"). Verified against the real engine
    (not a mock) by counting statements actually sent to Postgres -- a
    single SQL statement is inherently snapshot-consistent in Postgres, so
    this is what actually rules out the inconsistency the spec warns about.
    """
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 20)
    _make_reward_redeemed(db_session, child, -20)

    _ = child.id  # force any pending expire-on-commit reload before we start counting

    statements: list[str] = []

    def _capture(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    target = db_session.get_bind()
    event.listen(target, "before_cursor_execute", _capture)
    try:
        get_points(db_session, child)
    finally:
        event.remove(target, "before_cursor_execute", _capture)

    select_statements = [s for s in statements if s.strip().upper().startswith("SELECT")]
    assert len(select_statements) == 1
