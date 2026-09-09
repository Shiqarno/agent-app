import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    RewardRedemptionStatus,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)
from app.points_operations import InsufficientBalanceError, adjust_points
from app.reward_operations import (
    InsufficientPointsError,
    NotAnAdultError,
    RewardNotFoundError,
    RewardRedemptionNotActionableError,
    confirm_reward_redemption,
    get_available_balance,
    get_balance,
    get_pending_reward_requests,
    reject_reward_redemption,
    request_reward_redemption,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_reward(
    db_session: Session, creator: User, *, name: str = "Ice cream", cost_points: int = 30
) -> Reward:
    reward = Reward(name=name, cost_points=cost_points, created_by=creator.id)
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)
    return reward


def _grant_points(db_session: Session, user: User, amount: int) -> None:
    adult = User(name="Point Grantor", role=ADULT)
    db_session.add(adult)
    db_session.commit()
    db_session.refresh(adult)

    task = Task(title="Balance seed", reward_points=amount, created_by=adult.id)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id, user_id=user.id, status=TaskExecutionStatus.COMPLETED, reward_points=amount
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    db_session.add(
        PointTransaction(
            user_id=user.id,
            task_execution_id=execution.id,
            amount=amount,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    db_session.commit()


# =========================================================================================
# request_reward_redemption -- success
# =========================================================================================


def test_request_creates_a_pending_redemption(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)

    redemption, returned_reward, available = request_reward_redemption(db_session, child, reward.id)

    assert redemption.reward_id == reward.id
    assert redemption.user_id == child.id
    assert redemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION
    assert redemption.cost_points == 30
    assert returned_reward.id == reward.id
    assert available == 70


def test_request_stores_the_current_cost_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=45)

    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    assert redemption.cost_points == 45


def test_request_creates_no_reward_redeemed_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)

    request_reward_redemption(db_session, child, reward.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == child.id,
            PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
        )
    )
    assert count == 0


def test_request_reduces_available_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)

    request_reward_redemption(db_session, child, reward.id)

    assert get_available_balance(db_session, child.id) == 70


# =========================================================================================
# request_reward_redemption -- insufficient available balance
# =========================================================================================


def test_insufficient_available_balance_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        request_reward_redemption(db_session, child, reward.id)


def test_insufficient_available_balance_creates_no_redemption(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        request_reward_redemption(db_session, child, reward.id)

    assert db_session.query(RewardRedemption).filter_by(user_id=child.id).count() == 0


def test_a_rejected_request_does_not_change_frozen_amount(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        request_reward_redemption(db_session, child, reward.id)

    assert get_available_balance(db_session, child.id) == 50


def test_requesting_a_nonexistent_reward_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(RewardNotFoundError):
        request_reward_redemption(db_session, child, uuid.uuid4())


# =========================================================================================
# Frozen balance across two rewards
# =========================================================================================


def test_second_request_fails_once_the_first_exhausts_available_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Balance = 100. Reward A = 70 (requested, succeeds). Available = 30.
    Reward B = 40 (requested, fails)."""
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward_a = _make_reward(db_session, adult, name="Reward A", cost_points=70)
    reward_b = _make_reward(db_session, adult, name="Reward B", cost_points=40)

    request_reward_redemption(db_session, child, reward_a.id)
    assert get_available_balance(db_session, child.id) == 30

    with pytest.raises(InsufficientPointsError):
        request_reward_redemption(db_session, child, reward_b.id)

    assert db_session.query(RewardRedemption).filter_by(user_id=child.id).count() == 1


def test_reward_cost_change_after_request_does_not_affect_the_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)

    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    reward.cost_points = 40
    db_session.commit()

    confirmed, _, _ = confirm_reward_redemption(db_session, adult, redemption.id)

    assert confirmed.cost_points == 30
    transaction = db_session.query(PointTransaction).filter_by(redemption_id=redemption.id).one()
    assert transaction.amount == -30


# =========================================================================================
# get_pending_reward_requests
# =========================================================================================


def test_get_pending_reward_requests_returns_pending_only(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward_a = _make_reward(db_session, adult, name="Pending reward", cost_points=30)
    reward_b = _make_reward(db_session, adult, name="Confirmed reward", cost_points=20)

    pending, _, _ = request_reward_redemption(db_session, child, reward_a.id)
    confirmed_request, _, _ = request_reward_redemption(db_session, child, reward_b.id)
    confirm_reward_redemption(db_session, adult, confirmed_request.id)

    items = get_pending_reward_requests(db_session, adult)

    assert [r.id for r, _, _ in items] == [pending.id]


def test_get_pending_reward_requests_rejects_a_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        get_pending_reward_requests(db_session, child)


# =========================================================================================
# confirm_reward_redemption
# =========================================================================================


def test_confirm_transitions_to_confirmed_and_creates_exactly_one_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    confirmed, returned_reward, returned_child = confirm_reward_redemption(
        db_session, adult, redemption.id
    )

    assert confirmed.status == RewardRedemptionStatus.CONFIRMED
    assert returned_reward.id == reward.id
    assert returned_child.id == child.id

    transactions = db_session.query(PointTransaction).filter_by(redemption_id=redemption.id).all()
    assert len(transactions) == 1
    assert transactions[0].amount == -30
    assert transactions[0].reason == PointTransactionReason.REWARD_REDEEMED
    assert transactions[0].user_id == child.id


def test_confirm_releases_the_freeze_and_final_balance_is_correct(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)
    assert get_available_balance(db_session, child.id) == 70

    confirm_reward_redemption(db_session, adult, redemption.id)

    assert get_balance(db_session, child.id) == 70
    assert get_available_balance(db_session, child.id) == 70


def test_confirm_any_adult_may_process_a_request_no_ownership(
    make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, creator, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    confirmed, _, _ = confirm_reward_redemption(db_session, other_adult, redemption.id)

    assert confirmed.status == RewardRedemptionStatus.CONFIRMED


def test_child_cannot_confirm_a_request(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    with pytest.raises(NotAnAdultError):
        confirm_reward_redemption(db_session, child, redemption.id)

    db_session.refresh(redemption)
    assert redemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION


def test_confirming_a_nonexistent_request_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(RewardRedemptionNotActionableError):
        confirm_reward_redemption(db_session, adult, uuid.uuid4())


# =========================================================================================
# Issue #40: confirmation must never produce a negative ledger balance
# =========================================================================================


def test_valid_confirmation_still_works(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """The exact scenario from the issue's Test 3: balance=100, reward=80,
    request, confirm -> ledger=20, frozen=0, exactly one
    REWARD_REDEEMED(-80), redemption=CONFIRMED. The corrective fix must
    not break the normal, valid path.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=80)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    confirmed, _, _ = confirm_reward_redemption(db_session, adult, redemption.id)

    assert confirmed.status == RewardRedemptionStatus.CONFIRMED
    assert get_balance(db_session, child.id) == 20
    # No other pending requests -- frozen is 0, so available equals ledger.
    assert get_available_balance(db_session, child.id) == 20
    transactions = db_session.query(PointTransaction).filter_by(redemption_id=redemption.id).all()
    assert len(transactions) == 1
    assert transactions[0].amount == -80
    assert transactions[0].reason == PointTransactionReason.REWARD_REDEEMED


def test_confirm_fails_safely_when_the_ledger_can_no_longer_absorb_the_deduction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Represents ledger=100, frozen=80, then something outside the normal
    request/confirm/adjust path reduces the ledger below the frozen cost
    (this is exactly the class of state confirm_reward_redemption's own
    balance re-check exists to catch, as defense-in-depth independent of
    whether every other point-mutating path is individually correct).
    Confirmation must fail safely: no negative ledger, no partial
    redemption, no REWARD_REDEEMED transaction, and the request must stay
    PENDING_CONFIRMATION -- still actionable -- rather than silently
    advancing to a terminal state without its transaction.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=80)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    # Simulate an out-of-band ledger change that (unlike adjust_points,
    # which now itself refuses this) leaves the ledger unable to absorb
    # the still-pending 80-point freeze: 100 -> 30.
    db_session.add(
        PointTransaction(
            user_id=child.id,
            amount=-70,
            reason=PointTransactionReason.MANUAL_ADJUSTMENT,
            description="Out-of-band change bypassing adjust_points",
        )
    )
    db_session.commit()
    assert get_balance(db_session, child.id) == 30

    with pytest.raises(InsufficientPointsError):
        confirm_reward_redemption(db_session, adult, redemption.id)

    db_session.refresh(redemption)
    assert redemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION
    assert get_balance(db_session, child.id) == 30  # unchanged, never went negative
    txn_count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == child.id,
            PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
        )
    )
    assert txn_count == 0

    # The request remains actionable: it can still be confirmed once the
    # ledger recovers, or rejected outright.
    db_session.add(
        PointTransaction(
            user_id=child.id,
            amount=100,
            reason=PointTransactionReason.MANUAL_ADJUSTMENT,
            description="Balance recovers",
        )
    )
    db_session.commit()
    confirmed, _, _ = confirm_reward_redemption(db_session, adult, redemption.id)
    assert confirmed.status == RewardRedemptionStatus.CONFIRMED


# =========================================================================================
# reject_reward_redemption
# =========================================================================================


def test_reject_transitions_to_rejected_and_creates_no_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    rejected, returned_reward, returned_child = reject_reward_redemption(
        db_session, adult, redemption.id
    )

    assert rejected.status == RewardRedemptionStatus.REJECTED
    assert returned_reward.id == reward.id
    assert returned_child.id == child.id
    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.redemption_id == redemption.id)
    )
    assert count == 0


def test_reject_restores_the_available_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)
    assert get_available_balance(db_session, child.id) == 70

    reject_reward_redemption(db_session, adult, redemption.id)

    assert get_available_balance(db_session, child.id) == 100


def test_child_cannot_reject_a_request(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    with pytest.raises(NotAnAdultError):
        reject_reward_redemption(db_session, child, redemption.id)

    db_session.refresh(redemption)
    assert redemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION


# =========================================================================================
# Idempotency / terminal states
# =========================================================================================


def test_confirming_twice_creates_only_one_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    confirm_reward_redemption(db_session, adult, redemption.id)
    with pytest.raises(RewardRedemptionNotActionableError):
        confirm_reward_redemption(db_session, adult, redemption.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.redemption_id == redemption.id)
    )
    assert count == 1


def test_rejecting_twice_does_not_change_anything_further(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    reject_reward_redemption(db_session, adult, redemption.id)
    with pytest.raises(RewardRedemptionNotActionableError):
        reject_reward_redemption(db_session, adult, redemption.id)

    assert get_available_balance(db_session, child.id) == 100


def test_cannot_confirm_a_rejected_request(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    reject_reward_redemption(db_session, adult, redemption.id)

    with pytest.raises(RewardRedemptionNotActionableError):
        confirm_reward_redemption(db_session, adult, redemption.id)


def test_cannot_reject_a_confirmed_request(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=30)
    redemption, _, _ = request_reward_redemption(db_session, child, reward.id)

    confirm_reward_redemption(db_session, adult, redemption.id)

    with pytest.raises(RewardRedemptionNotActionableError):
        reject_reward_redemption(db_session, adult, redemption.id)


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_requests_cannot_overspend_the_available_balance() -> None:
    """balance=100, two concurrent requests each costing 70: exactly one
    succeeds, exactly one PENDING_CONFIRMATION redemption exists. Real
    independently-committing sessions, matching this project's established
    concurrency test pattern.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Balance seed", reward_points=100, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.COMPLETED, reward_points=100
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    setup_session.add(
        PointTransaction(
            user_id=child.id,
            task_execution_id=execution.id,
            amount=100,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    setup_session.commit()

    reward_a = Reward(name="Reward A", cost_points=70, created_by=adult.id)
    reward_b = Reward(name="Reward B", cost_points=70, created_by=adult.id)
    setup_session.add_all([reward_a, reward_b])
    setup_session.commit()
    setup_session.refresh(reward_a)
    setup_session.refresh(reward_b)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(reward_id: uuid.UUID) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                user = session.get(User, child.id)
                assert user is not None
                request_reward_redemption(session, user, reward_id)
                results.append("success")
            except InsufficientPointsError:
                results.append("rejected")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(reward_a.id,)),
            threading.Thread(target=attempt, args=(reward_b.id,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["rejected", "success"]

        setup_session.expire_all()
        pending_count = setup_session.scalar(
            select(func.count())
            .select_from(RewardRedemption)
            .where(
                RewardRedemption.user_id == child.id,
                RewardRedemption.status == RewardRedemptionStatus.PENDING_CONFIRMATION,
            )
        )
        assert pending_count == 1

        available = get_available_balance(setup_session, child.id)
        assert available == 30
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(user_id=child.id).delete()
        setup_session.query(RewardRedemption).filter_by(user_id=child.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(Reward).filter(Reward.id.in_([reward_a.id, reward_b.id])).delete(
            synchronize_session=False
        )
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()


# =========================================================================================
# Issue #40: concurrency -- confirmation vs manual adjustment
# =========================================================================================


def test_concurrent_confirmation_and_manual_adjustment_never_go_negative() -> None:
    """The issue's Scenario 2: balance=100, an 80-cost request already
    pending (frozen=80), then a concurrent Confirm (-80) and a -50 manual
    adjustment race for the same User. Confirming a request that's already
    frozen never changes *available* balance (frozen decreases by exactly
    what the ledger decreases by), so the adjustment's outcome is the same
    regardless of ordering here -- but the invariant under test is that
    the final ledger balance is never negative and exactly one
    REWARD_REDEEMED transaction exists, not a specific interleaving. Real
    independently-committing sessions, matching this project's established
    concurrency test pattern.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    task = Task(title="Balance seed", reward_points=100, created_by=adult.id)
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.COMPLETED, reward_points=100
    )
    setup_session.add(execution)
    setup_session.commit()
    setup_session.refresh(execution)

    setup_session.add(
        PointTransaction(
            user_id=child.id,
            task_execution_id=execution.id,
            amount=100,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    setup_session.commit()

    reward = Reward(name="Contested reward", cost_points=80, created_by=adult.id)
    setup_session.add(reward)
    setup_session.commit()
    setup_session.refresh(reward)

    redemption, _, _ = request_reward_redemption(setup_session, child, reward.id)

    try:
        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def attempt_confirm() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                actor = session.get(User, adult.id)
                assert actor is not None
                confirm_reward_redemption(session, actor, redemption.id)
                results["confirm"] = "success"
            except (InsufficientPointsError, RewardRedemptionNotActionableError):
                results["confirm"] = "rejected"
            finally:
                session.close()

        def attempt_adjustment() -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                actor = session.get(User, adult.id)
                target = session.get(User, child.id)
                assert actor is not None
                assert target is not None
                adjust_points(session, actor, target, amount=-50, description="Concurrent removal")
                results["adjustment"] = "success"
            except InsufficientBalanceError:
                results["adjustment"] = "rejected"
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt_confirm),
            threading.Thread(target=attempt_adjustment),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        setup_session.expire_all()
        final_balance = setup_session.scalar(
            select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
                PointTransaction.user_id == child.id
            )
        )
        assert final_balance is not None
        # The core invariant this Issue exists to guarantee.
        assert final_balance >= 0

        redeemed_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(
                PointTransaction.user_id == child.id,
                PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
            )
        )
        assert redeemed_count == 1

        # Deterministic in this specific scenario (see docstring): the
        # confirmation never competes with the adjustment for available
        # balance, so it always succeeds and the adjustment (50 > the 20
        # left over after the 80-point confirmation) always fails.
        assert results["confirm"] == "success"
        assert results["adjustment"] == "rejected"
        assert final_balance == 20
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(user_id=child.id).delete()
        setup_session.query(RewardRedemption).filter_by(user_id=child.id).delete()
        setup_session.query(TaskExecution).filter_by(id=execution.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(Reward).filter_by(id=reward.id).delete()
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
