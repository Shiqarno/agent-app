import uuid
from collections.abc import Callable

import pytest
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
from app.reward_operations import (
    InvalidRewardInputError,
    NotAnAdultError,
    RewardNotFoundError,
    create_reward,
    redeem_reward,
    update_reward,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_reward(
    db_session: Session,
    creator: User,
    *,
    name: str = "Ice cream",
    description: str | None = "Vanilla or chocolate",
    cost_points: int = 100,
) -> Reward:
    reward = Reward(
        name=name, description=description, cost_points=cost_points, created_by=creator.id
    )
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)
    return reward


# =========================================================================================
# create_reward
# =========================================================================================


def test_adult_can_create_a_reward(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    reward = create_reward(
        db_session, adult, name="Ice cream", description="Any flavor", cost_points=100
    )

    assert reward.name == "Ice cream"
    assert reward.description == "Any flavor"
    assert reward.cost_points == 100


def test_child_cannot_create_a_reward(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        create_reward(db_session, child, name="Ice cream", description=None, cost_points=100)


def test_created_reward_has_created_by_set_to_the_creating_adult(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    reward = create_reward(db_session, adult, name="Ice cream", description=None, cost_points=100)

    assert reward.created_by == adult.id


def test_create_reward_allows_no_description(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    reward = create_reward(db_session, adult, name="Ice cream", description=None, cost_points=100)

    assert reward.description is None


def test_create_reward_rejects_a_blank_name(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidRewardInputError):
        create_reward(db_session, adult, name="   ", description=None, cost_points=100)


def test_create_reward_rejects_non_positive_cost(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidRewardInputError):
        create_reward(db_session, adult, name="Ice cream", description=None, cost_points=0)


def test_create_reward_error_message_is_human_readable(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidRewardInputError) as exc_info:
        create_reward(db_session, adult, name="", description=None, cost_points=100)

    assert "Value error" not in exc_info.value.message


# =========================================================================================
# update_reward
# =========================================================================================


def test_adult_can_update_a_reward(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult, name="Ice cream", cost_points=100)

    updated = update_reward(db_session, adult, reward.id, name="Deluxe ice cream")

    assert updated.name == "Deluxe ice cream"


def test_any_adult_can_update_a_reward_created_by_another_adult(
    make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    reward = _make_reward(db_session, creator)

    updated = update_reward(db_session, other_adult, reward.id, name="Renamed")

    assert updated.name == "Renamed"


def test_child_cannot_update_a_reward(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    reward = _make_reward(db_session, adult)

    with pytest.raises(NotAnAdultError):
        update_reward(db_session, child, reward.id, name="Hacked")


def test_update_reward_name(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult, name="Ice cream")

    updated = update_reward(db_session, adult, reward.id, name="Sundae")

    assert updated.name == "Sundae"


def test_update_reward_description(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult, description="Old description")

    updated = update_reward(db_session, adult, reward.id, description="New description")

    assert updated.description == "New description"


def test_update_reward_cost(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult, cost_points=100)

    updated = update_reward(db_session, adult, reward.id, cost_points=250)

    assert updated.cost_points == 250


def test_update_reward_leaves_unspecified_fields_untouched(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult, name="Ice cream", description="Yum", cost_points=100)

    updated = update_reward(db_session, adult, reward.id, cost_points=150)

    assert updated.name == "Ice cream"
    assert updated.description == "Yum"
    assert updated.cost_points == 150


def test_update_reward_does_not_change_created_by(
    make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    reward = _make_reward(db_session, creator)

    updated = update_reward(db_session, other_adult, reward.id, name="Renamed")

    assert updated.created_by == creator.id


def test_update_reward_does_not_change_created_at(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult)
    original_created_at = reward.created_at

    updated = update_reward(db_session, adult, reward.id, name="Renamed")

    assert updated.created_at == original_created_at


def test_update_missing_reward_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(RewardNotFoundError):
        update_reward(db_session, adult, uuid.uuid4(), name="Anything")


def test_update_reward_rejects_a_blank_name(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult)

    with pytest.raises(InvalidRewardInputError):
        update_reward(db_session, adult, reward.id, name="   ")


def test_update_reward_rejects_non_positive_cost(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    reward = _make_reward(db_session, adult)

    with pytest.raises(InvalidRewardInputError):
        update_reward(db_session, adult, reward.id, cost_points=-5)


# =========================================================================================
# Historical redemption behavior
# =========================================================================================


def test_changing_reward_cost_does_not_affect_historical_redemption_snapshot(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    reward = _make_reward(db_session, adult, cost_points=100)

    # Grant the child enough points to redeem at the old cost.
    task = Task(title="Seed", reward_points=100, created_by=adult.id)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    execution = TaskExecution(
        task_id=task.id, user_id=child.id, status=TaskExecutionStatus.COMPLETED, reward_points=100
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    db_session.add(
        PointTransaction(
            user_id=child.id,
            task_execution_id=execution.id,
            amount=100,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    db_session.commit()

    old_redemption, _, _ = redeem_reward(db_session, child, reward.id)
    assert old_redemption.cost_points == 100

    update_reward(db_session, adult, reward.id, cost_points=200)

    db_session.refresh(old_redemption)
    assert old_redemption.cost_points == 100  # historical snapshot unchanged

    redemption_from_db = db_session.get(RewardRedemption, old_redemption.id)
    assert redemption_from_db is not None
    assert redemption_from_db.cost_points == 100
