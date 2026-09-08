import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.handlers.rewards import (
    _INSUFFICIENT_POINTS_TEXT,
    _NOT_A_CHILD_TEXT,
    _NOT_CONNECTED_TEXT,
    _REWARD_UNAVAILABLE_TEXT,
    _redeem,
    _rewards_view,
)
from app.telegram.keyboards.rewards import GET_CALLBACK_PREFIX
from app.telegram.views.rewards import AVAILABLE_REWARDS_HEADING, NO_REWARDS_TEXT_PREFIX
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """Same rationale as test_telegram_tasks.py / test_telegram_confirmations.py:
    the handlers under test open their own `SessionLocal()`, a genuinely
    separate, independently-committing connection from the savepoint-
    isolated `db_session` fixture, so setup here must use a real session too.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []
        self.task_ids: list[uuid.UUID] = []
        self.reward_ids: list[uuid.UUID] = []

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    def make_reward(
        self, creator: User, *, name: str = "Ice cream", cost_points: int = 100
    ) -> Reward:
        reward = Reward(name=name, cost_points=cost_points, created_by=creator.id)
        self.session.add(reward)
        self.session.commit()
        self.session.refresh(reward)
        self.reward_ids.append(reward.id)
        return reward

    def grant_points(self, user: User, amount: int) -> None:
        task = Task(title="Balance seed", reward_points=amount, created_by=user.id)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task_ids.append(task.id)

        execution = TaskExecution(
            task_id=task.id,
            user_id=user.id,
            status=TaskExecutionStatus.COMPLETED,
            reward_points=amount,
        )
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)

        self.session.add(
            PointTransaction(
                user_id=user.id,
                task_execution_id=execution.id,
                amount=amount,
                reason=PointTransactionReason.TASK_COMPLETED,
            )
        )
        self.session.commit()

    def connect(self, user: User, telegram_id: int) -> None:
        token = insert_activation(self.session, user.id)
        self.session.commit()
        activate_telegram_identity(self.session, token, telegram_id)


@pytest.fixture
def real(db_session: Session) -> Iterator[RealData]:
    del db_session
    session = SessionLocal()
    data = RealData(session)
    try:
        yield data
    finally:
        session.rollback()
        if data.user_ids:
            session.query(PointTransaction).filter(
                PointTransaction.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
            session.query(RewardRedemption).filter(
                RewardRedemption.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
        if data.task_ids:
            session.query(TaskExecution).filter(TaskExecution.task_id.in_(data.task_ids)).delete(
                synchronize_session=False
            )
            session.query(Task).filter(Task.id.in_(data.task_ids)).delete(synchronize_session=False)
        if data.reward_ids:
            session.query(Reward).filter(Reward.id.in_(data.reward_ids)).delete(
                synchronize_session=False
            )
        if data.user_ids:
            session.query(TelegramIdentity).filter(
                TelegramIdentity.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
            session.query(UserActivation).filter(UserActivation.user_id.in_(data.user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(data.user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


# =========================================================================================
# Rendering
# =========================================================================================


def test_child_can_render_rewards(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 320)
    reward = real.make_reward(child, name="Ice cream", cost_points=100)

    text, keyboard = _rewards_view(telegram_id)

    assert text.startswith(AVAILABLE_REWARDS_HEADING)
    assert "Ice cream" in text
    assert "100" in text
    assert "320" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == f"{GET_CALLBACK_PREFIX}{reward.id}"
    assert keyboard.inline_keyboard[0][0].text == "Ice cream · 100 pts"


def test_unaffordable_reward_gets_no_button(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 50)
    real.make_reward(child, name="New game", cost_points=500)

    text, keyboard = _rewards_view(telegram_id)

    assert "New game" in text
    assert "Not enough points" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_empty_catalog_renders_correctly(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _rewards_view(telegram_id)

    assert NO_REWARDS_TEXT_PREFIX in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_adult_does_not_get_the_child_rewards_ux(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.make_reward(adult)

    text, keyboard = _rewards_view(telegram_id)

    assert text == _NOT_A_CHILD_TEXT
    assert keyboard is None


def test_rewards_view_for_unconnected_account() -> None:
    text, keyboard = _rewards_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Get / redemption
# =========================================================================================


def test_get_redeems_and_shows_remaining_balance(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 320)
    reward = real.make_reward(child, name="Ice cream", cost_points=100)

    toast, success, text, keyboard = _redeem(telegram_id, str(reward.id))

    assert success is True
    assert "Ice cream" in toast
    assert "220" in toast
    real.session.expire_all()
    redemption = (
        real.session.query(RewardRedemption).filter_by(reward_id=reward.id, user_id=child.id).one()
    )
    assert redemption.cost_points == 100
    # Refreshed view reflects the new balance.
    assert "220" in text
    assert keyboard is not None


def test_get_with_insufficient_points_is_a_friendly_error(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 50)
    reward = real.make_reward(child, name="New game", cost_points=500)

    toast, success, text, keyboard = _redeem(telegram_id, str(reward.id))

    assert success is False
    assert toast == _INSUFFICIENT_POINTS_TEXT
    real.session.expire_all()
    assert (
        real.session.query(RewardRedemption)
        .filter_by(reward_id=reward.id, user_id=child.id)
        .count()
        == 0
    )
    assert keyboard is not None


def test_get_on_a_stale_reward_id_is_a_friendly_error(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 100)

    toast, success, _, keyboard = _redeem(telegram_id, str(uuid.uuid4()))

    assert success is False
    assert toast == _REWARD_UNAVAILABLE_TEXT
    assert keyboard is not None


def test_get_with_a_bogus_reward_id_does_not_crash(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    toast, success, _, keyboard = _redeem(telegram_id, "not-a-uuid")

    assert success is False
    assert toast == _REWARD_UNAVAILABLE_TEXT
    assert keyboard is not None


def test_get_for_unconnected_account() -> None:
    toast, success, _, keyboard = _redeem(_next_telegram_id(), str(uuid.uuid4()))

    assert success is False
    assert toast == _NOT_CONNECTED_TEXT
    assert keyboard is None


def test_adult_cannot_redeem_via_a_crafted_callback(real: RealData) -> None:
    """Issue #26 Authorization: the Telegram gate is presentation-only, but
    a manually crafted callback must still be rejected -- here the handler
    itself gates by role before ever calling the Application layer.
    """
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.grant_points(adult, 100)
    reward = real.make_reward(adult, cost_points=100)

    toast, success, _, _ = _redeem(telegram_id, str(reward.id))

    assert success is False
    assert toast == _NOT_A_CHILD_TEXT
    real.session.expire_all()
    assert (
        real.session.query(RewardRedemption)
        .filter_by(reward_id=reward.id, user_id=adult.id)
        .count()
        == 0
    )


def test_get_uses_the_current_reward_cost_not_a_stale_one(real: RealData) -> None:
    """Issue #26 "Stale reward cost": the callback only identifies the
    reward; the redeemed cost must come from current state, not whatever
    was true when the button was rendered.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 100)
    reward = real.make_reward(child, cost_points=100)
    # Simulate the cost changing after the Rewards screen was rendered but
    # before the (still-valid-looking) Get callback is handled.
    reward.cost_points = 150
    real.session.commit()

    toast, success, _, _ = _redeem(telegram_id, str(reward.id))

    assert success is False
    assert toast == _INSUFFICIENT_POINTS_TEXT
