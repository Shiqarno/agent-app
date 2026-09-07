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
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)
from app.reward_operations import (
    InsufficientPointsError,
    RewardNotFoundError,
    get_balance,
    get_rewards,
    redeem_reward,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_reward(
    db_session: Session, creator: User, *, name: str = "Ice cream", cost_points: int = 100
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
# get_rewards
# =========================================================================================


def test_child_can_retrieve_the_global_catalog(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    reward = _make_reward(db_session, adult)

    rewards, _ = get_rewards(db_session, child)

    assert [r.id for r in rewards] == [reward.id]


def test_adult_can_also_retrieve_the_catalog(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Not scoped by an Adult/Child relationship -- every User sees the
    same catalog (Issue #26 "Catalog" test requirement).
    """
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")
    reward = _make_reward(db_session, adult)

    rewards, _ = get_rewards(db_session, other_adult)

    assert [r.id for r in rewards] == [reward.id]


def test_get_rewards_returns_the_current_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _grant_points(db_session, child, 250)

    _, balance = get_rewards(db_session, child)

    assert balance == 250


# =========================================================================================
# redeem_reward -- success
# =========================================================================================


def test_redeem_with_sufficient_balance_creates_a_redemption(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=100)

    redemption, returned_reward, remaining_balance = redeem_reward(db_session, child, reward.id)

    assert redemption.reward_id == reward.id
    assert redemption.user_id == child.id
    assert redemption.cost_points == 100
    assert returned_reward.id == reward.id
    assert remaining_balance == 0


def test_redeem_creates_exactly_one_negative_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=100)

    redemption, _, _ = redeem_reward(db_session, child, reward.id)

    transactions = db_session.query(PointTransaction).filter_by(redemption_id=redemption.id).all()
    assert len(transactions) == 1
    assert transactions[0].amount == -100
    assert transactions[0].reason == PointTransactionReason.REWARD_REDEEMED
    assert transactions[0].user_id == child.id


def test_redeem_transaction_links_to_the_redemption(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=100)

    redemption, _, _ = redeem_reward(db_session, child, reward.id)

    transaction = db_session.query(PointTransaction).filter_by(redemption_id=redemption.id).one()
    assert transaction.redemption_id == redemption.id
    assert transaction.task_execution_id is None


def test_redeem_resulting_balance_is_correct(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 250)
    reward = _make_reward(db_session, adult, cost_points=100)

    _, _, remaining_balance = redeem_reward(db_session, child, reward.id)

    assert remaining_balance == 150
    assert get_balance(db_session, child.id) == 150


# =========================================================================================
# redeem_reward -- insufficient balance
# =========================================================================================


def test_insufficient_balance_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        redeem_reward(db_session, child, reward.id)


def test_insufficient_balance_creates_no_redemption(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        redeem_reward(db_session, child, reward.id)

    assert db_session.query(RewardRedemption).filter_by(user_id=child.id).count() == 0


def test_insufficient_balance_creates_no_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = _make_reward(db_session, adult, cost_points=100)

    with pytest.raises(InsufficientPointsError):
        redeem_reward(db_session, child, reward.id)

    count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == child.id,
            PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
        )
    )
    assert count == 0


def test_redeeming_a_nonexistent_reward_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    with pytest.raises(RewardNotFoundError):
        redeem_reward(db_session, child, uuid.uuid4())


# =========================================================================================
# redeem_reward -- current cost, not a stale/callback-supplied one
# =========================================================================================


def test_redeem_uses_the_current_reward_cost(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 150)
    reward = _make_reward(db_session, adult, cost_points=100)
    reward.cost_points = 150  # changed after the Child's Rewards screen was rendered
    db_session.commit()

    redemption, _, remaining_balance = redeem_reward(db_session, child, reward.id)

    assert redemption.cost_points == 150
    assert remaining_balance == 0


def test_redeem_at_increased_cost_can_now_be_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """A stale Get button rendered when the reward was affordable must not
    force the old (lower) cost once the Application layer re-checks.
    """
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, adult, cost_points=100)
    reward.cost_points = 150
    db_session.commit()

    with pytest.raises(InsufficientPointsError):
        redeem_reward(db_session, child, reward.id)


# =========================================================================================
# Authorization -- any User, no ownership relationship
# =========================================================================================


def test_any_user_role_can_redeem_matching_existing_web_semantics(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """The existing Web `/redeem` endpoint has no role restriction; the
    extracted Application operation preserves that (Issue #26's "Adult
    doesn't get Get" is a Telegram presentation choice, not a new
    Application-layer rule -- see app/reward_operations.py).
    """
    adult = make_user(ADULT)
    _grant_points(db_session, adult, 100)
    reward = _make_reward(db_session, adult, cost_points=100)

    redemption, _, _ = redeem_reward(db_session, adult, reward.id)

    assert redemption.user_id == adult.id


def test_redemption_is_not_scoped_by_reward_ownership(
    make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    reward = _make_reward(db_session, creator, cost_points=100)

    redemption, _, _ = redeem_reward(db_session, child, reward.id)

    assert redemption.reward_id == reward.id


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_redemptions_cannot_overspend_the_balance() -> None:
    """balance=100, two concurrent redemptions each costing 100: exactly one
    succeeds, exactly one Redemption and one negative PointTransaction
    exist, final balance is 0. Real independently-committing sessions,
    matching this project's established concurrency test pattern.
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

    reward_a = Reward(name="Reward A", cost_points=100, created_by=adult.id)
    reward_b = Reward(name="Reward B", cost_points=100, created_by=adult.id)
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
                redeem_reward(session, user, reward_id)
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
        final_balance = setup_session.scalar(
            select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
                PointTransaction.user_id == child.id
            )
        )
        assert final_balance == 0

        redemption_count = setup_session.scalar(
            select(func.count())
            .select_from(RewardRedemption)
            .where(RewardRedemption.user_id == child.id)
        )
        assert redemption_count == 1

        negative_transaction_count = setup_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(
                PointTransaction.user_id == child.id,
                PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
            )
        )
        assert negative_transaction_count == 1
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
