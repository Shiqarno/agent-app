import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
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
from app.points_operations import (
    PAGE_SIZE,
    InsufficientBalanceError,
    InvalidAdjustmentError,
    NotAuthorizedError,
    adjust_points,
    get_points,
)
from app.reward_operations import redeem_reward

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


# =========================================================================================
# Issue #31: viewing a target User's Points
# =========================================================================================


def test_adult_can_view_a_childs_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 30, title="Clean room")

    view = get_points(db_session, adult, target_user=child)

    assert view.balance == 30
    assert view.transactions[0].description == "Clean room"


def test_adult_cannot_view_another_adults_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")

    with pytest.raises(NotAuthorizedError):
        get_points(db_session, adult, target_user=other_adult)


def test_child_cannot_view_another_users_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")

    with pytest.raises(NotAuthorizedError):
        get_points(db_session, child, target_user=other_child)


def test_child_cannot_view_an_adults_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    adult = make_user(ADULT)

    with pytest.raises(NotAuthorizedError):
        get_points(db_session, child, target_user=adult)


def test_adult_can_still_view_their_own_points_via_target_user(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    _make_task_completed(db_session, adult, 15)

    view = get_points(db_session, adult, target_user=adult)

    assert view.balance == 15


def test_child_can_still_view_their_own_points_via_target_user(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 15)

    view = get_points(db_session, child, target_user=child)

    assert view.balance == 15


# =========================================================================================
# Issue #31: adjust_points -- authorization
# =========================================================================================


def test_adult_can_adjust_a_childs_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    transaction, new_balance = adjust_points(
        db_session, adult, child, amount=100, description="Bonus for helping with dinner"
    )

    assert transaction.reason == PointTransactionReason.MANUAL_ADJUSTMENT
    assert new_balance == 100


def test_child_cannot_adjust_points(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    other_child = make_user(CHILD, "Other Child")

    with pytest.raises(NotAuthorizedError):
        adjust_points(db_session, child, other_child, amount=10, description="Nice try")


def test_adult_cannot_adjust_another_adults_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")

    with pytest.raises(NotAuthorizedError):
        adjust_points(db_session, adult, other_adult, amount=10, description="Nice try")


def test_adult_cannot_adjust_their_own_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    with pytest.raises(NotAuthorizedError):
        adjust_points(db_session, adult, adult, amount=10, description="Self bonus")


# =========================================================================================
# Issue #31: adjust_points -- add
# =========================================================================================


def test_add_creates_exactly_one_manual_adjustment_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    adjust_points(db_session, adult, child, amount=100, description="Bonus")

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == child.id,
            PointTransaction.reason == PointTransactionReason.MANUAL_ADJUSTMENT,
        )
    )
    assert count == 1


def test_add_increases_balance_correctly(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 50)

    _, new_balance = adjust_points(db_session, adult, child, amount=100, description="Bonus")

    assert new_balance == 150
    assert get_points(db_session, adult, target_user=child).balance == 150


def test_add_persists_the_description(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    transaction, _ = adjust_points(
        db_session, adult, child, amount=100, description="Bonus for helping with dinner"
    )

    assert transaction.description == "Bonus for helping with dinner"


# =========================================================================================
# Issue #31: adjust_points -- remove
# =========================================================================================


def test_remove_creates_exactly_one_manual_adjustment_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)

    adjust_points(db_session, adult, child, amount=-50, description="Penalty")

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == child.id,
            PointTransaction.reason == PointTransactionReason.MANUAL_ADJUSTMENT,
        )
    )
    assert count == 1


def test_remove_decreases_balance_correctly(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)

    transaction, new_balance = adjust_points(
        db_session, adult, child, amount=-50, description="Penalty for breaking the rule"
    )

    assert transaction.amount == -50
    assert new_balance == 50
    assert get_points(db_session, adult, target_user=child).balance == 50


def test_remove_persists_the_description(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)

    transaction, _ = adjust_points(
        db_session, adult, child, amount=-50, description="Penalty for breaking the rule"
    )

    assert transaction.description == "Penalty for breaking the rule"


# =========================================================================================
# Issue #31: adjust_points -- validation
# =========================================================================================


def test_zero_amount_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    with pytest.raises(InvalidAdjustmentError):
        adjust_points(db_session, adult, child, amount=0, description="No-op")


def test_blank_description_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    with pytest.raises(InvalidAdjustmentError):
        adjust_points(db_session, adult, child, amount=10, description="")


def test_whitespace_only_description_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    with pytest.raises(InvalidAdjustmentError):
        adjust_points(db_session, adult, child, amount=10, description="   ")


def test_failed_validation_creates_no_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    for amount, description in [(0, "valid"), (10, ""), (10, "   ")]:
        try:
            adjust_points(db_session, adult, child, amount=amount, description=description)
        except InvalidAdjustmentError:
            pass

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.user_id == child.id)
    )
    assert count == 0


# =========================================================================================
# Issue #31: adjust_points -- negative balance invariant
# =========================================================================================


def test_deduction_that_would_go_negative_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 50)

    with pytest.raises(InsufficientBalanceError):
        adjust_points(db_session, adult, child, amount=-100, description="Too much")


def test_rejected_deduction_creates_no_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 50)

    with pytest.raises(InsufficientBalanceError):
        adjust_points(db_session, adult, child, amount=-100, description="Too much")

    assert get_points(db_session, adult, target_user=child).balance == 50


def test_deduction_that_exactly_zeroes_the_balance_is_allowed(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 50)

    _, new_balance = adjust_points(db_session, adult, child, amount=-50, description="Exact")

    assert new_balance == 0


# =========================================================================================
# Issue #31: historical data untouched
# =========================================================================================


def test_existing_task_completed_transaction_has_a_null_description_column(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    transaction = _make_task_completed(db_session, child, 20, title="Clean room")

    assert transaction.description is None


def test_existing_reward_redeemed_transaction_has_a_null_description_column(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 100)
    transaction = _make_reward_redeemed(db_session, child, -100, name="Ice cream")

    assert transaction.description is None


def test_manual_adjustment_surfaces_its_own_description_in_history(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)

    adjust_points(db_session, adult, child, amount=100, description="Bonus for helping with dinner")

    view = get_points(db_session, adult, target_user=child)

    assert view.transactions[0].description == "Bonus for helping with dinner"
    assert view.transactions[0].amount == 100


def test_a_later_manual_adjustment_does_not_change_an_earlier_redemptions_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Cross-check the existing historical-snapshot invariant (Issue #30):
    a manual Point adjustment must not touch RewardRedemption.cost_points
    for a redemption that already happened -- only the ledger balance
    changes, never a historical record.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _make_task_completed(db_session, child, 500)
    reward = Reward(name="Toy", cost_points=500, created_by=adult.id)
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)

    redemption, _, _ = redeem_reward(db_session, child, reward.id)
    assert redemption.cost_points == 500

    reward.cost_points = 700
    db_session.commit()
    adjust_points(db_session, adult, child, amount=200, description="Unrelated bonus")

    db_session.refresh(redemption)
    assert redemption.cost_points == 500


# =========================================================================================
# Issue #31: concurrency
# =========================================================================================


def test_concurrent_removals_cannot_overspend_the_balance() -> None:
    """balance=50, two concurrent removals of 40 each: exactly one
    succeeds, exactly one MANUAL_ADJUSTMENT transaction exists, final
    balance is 10. Mirrors test_reward_operations's
    test_concurrent_redemptions_cannot_overspend_the_balance -- real
    independently-committing sessions, this project's established
    concurrency test pattern, proving adjust_points's row lock coexists
    correctly with (and is exercised the same way as) redeem_reward's.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Balance seed", reward_points=50, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.COMPLETED, reward_points=50
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    setup_session.add(
        PointTransaction(
            user_id=child.id,
            task_execution_id=execution.id,
            amount=50,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    setup_session.commit()

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                actor = session.get(User, adult.id)
                target = session.get(User, child.id)
                assert actor is not None
                assert target is not None
                adjust_points(session, actor, target, amount=-40, description="Concurrent removal")
                results.append("success")
            except InsufficientBalanceError:
                results.append("rejected")
            finally:
                session.close()

        threads = [threading.Thread(target=attempt), threading.Thread(target=attempt)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["rejected", "success"]

        setup_session.expire_all()
        final_balance = setup_session.scalar(
            select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
                PointTransaction.user_id == child.id
            )
        )
        assert final_balance == 10

        adjustment_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(
                PointTransaction.user_id == child.id,
                PointTransaction.reason == PointTransactionReason.MANUAL_ADJUSTMENT,
            )
        )
        assert adjustment_count == 1
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(user_id=child.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
