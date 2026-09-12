import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

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
from app.points_operations import PAGE_SIZE
from app.telegram.handlers.points import _NOT_A_CHILD_TEXT, _NOT_CONNECTED_TEXT, _points_view
from app.telegram.keyboards.points import LIST_CALLBACK_DATA, OLDER_CALLBACK_PREFIX
from app.telegram.views.points import NO_TRANSACTIONS_TEXT
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """Same rationale as test_telegram_tasks.py / test_telegram_confirmations.py
    / test_telegram_rewards.py: the handlers under test open their own
    `SessionLocal()`, a genuinely separate, independently-committing
    connection from the savepoint-isolated `db_session` fixture, so setup
    here must use a real session too.
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

    def task_completed(
        self,
        user: User,
        amount: int,
        *,
        title: str = "Clean room",
        created_at: datetime | None = None,
    ) -> PointTransaction:
        task = Task(title=title, reward_points=amount, created_by=user.id)
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

        txn = PointTransaction(
            user_id=user.id,
            task_execution_id=execution.id,
            amount=amount,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
        if created_at is not None:
            txn.created_at = created_at
        self.session.add(txn)
        self.session.commit()
        self.session.refresh(txn)
        return txn

    def reward_redeemed(
        self,
        user: User,
        amount: int,
        *,
        name: str = "Ice cream",
        created_at: datetime | None = None,
    ) -> PointTransaction:
        reward = Reward(name=name, cost_points=abs(amount), created_by=user.id)
        self.session.add(reward)
        self.session.commit()
        self.session.refresh(reward)
        self.reward_ids.append(reward.id)

        redemption = RewardRedemption(reward_id=reward.id, user_id=user.id, cost_points=abs(amount))
        self.session.add(redemption)
        self.session.commit()
        self.session.refresh(redemption)

        txn = PointTransaction(
            user_id=user.id,
            redemption_id=redemption.id,
            amount=amount,
            reason=PointTransactionReason.REWARD_REDEEMED,
        )
        if created_at is not None:
            txn.created_at = created_at
        self.session.add(txn)
        self.session.commit()
        self.session.refresh(txn)
        return txn

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


def test_child_can_render_points(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 100, title="Clean room")

    text, keyboard = _points_view(telegram_id, None)

    assert "Баланс" in text
    assert "💰 100" in text
    assert "Clean room" in text
    assert keyboard is not None


def test_balance_is_rendered(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 100)
    real.reward_redeemed(child, -40)

    text, _ = _points_view(telegram_id, None)

    assert "💰 60" in text


def test_task_completed_shows_the_task_title(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 20, title="Wash dishes")

    text, _ = _points_view(telegram_id, None)

    assert "Wash dishes" in text
    assert "+💰 20" in text
    assert "TASK_COMPLETED" not in text


def test_reward_redeemed_shows_the_reward_name(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 100)
    real.reward_redeemed(child, -100, name="Ice cream")

    text, _ = _points_view(telegram_id, None)

    assert "Ice cream" in text
    assert "-💰 100" in text
    assert "REWARD_REDEEMED" not in text


def test_empty_history_renders_correctly(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _points_view(telegram_id, None)

    assert "💰 0" in text
    assert NO_TRANSACTIONS_TEXT in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_adult_does_not_get_the_child_points_ux(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.task_completed(adult, 20)

    text, keyboard = _points_view(telegram_id, None)

    assert text == _NOT_A_CHILD_TEXT
    assert keyboard is None


def test_points_view_for_unconnected_account() -> None:
    text, keyboard = _points_view(_next_telegram_id(), None)

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Pagination
# =========================================================================================


def test_older_button_present_when_more_history_exists(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(PAGE_SIZE + 1):
        real.task_completed(child, 1, title=f"Task {i}", created_at=base.replace(day=i + 1))

    _, keyboard = _points_view(telegram_id, None)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].text == "Ранее"


def test_older_loads_the_next_page(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(PAGE_SIZE + 1):
        real.task_completed(child, 1, title=f"Task {i}", created_at=base.replace(day=i + 1))

    first_text, first_keyboard = _points_view(telegram_id, None)
    assert first_keyboard is not None
    raw_cursor = first_keyboard.inline_keyboard[0][0].callback_data.removeprefix(
        OLDER_CALLBACK_PREFIX
    )
    cursor = uuid.UUID(raw_cursor)

    second_text, second_keyboard = _points_view(telegram_id, cursor)

    # The oldest task (day 1, "Task 0") only appears on the second page.
    assert "Task 0" not in first_text
    assert "Task 0" in second_text
    assert second_keyboard is not None
    assert len(second_keyboard.inline_keyboard) == 0


def test_a_crafted_cursor_cannot_expose_another_users_history(real: RealData) -> None:
    """Issue #27 Authorization: a pagination cursor is routing state, not a
    security boundary -- pointing it at another user's transaction id must
    not leak that user's data, since the query is always scoped to the
    resolved User.
    """
    child = real.make_user(CHILD)
    other = real.make_user(CHILD, "Other Child")
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 20, title="Mine")
    other_txn = real.task_completed(other, 999, title="Not mine")

    text, _ = _points_view(telegram_id, other_txn.id)

    assert "Not mine" not in text
    assert "999" not in text


def test_stale_or_invalid_cursor_falls_back_to_the_first_page(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.task_completed(child, 20, title="Clean room")

    text, _ = _points_view(telegram_id, uuid.uuid4())

    assert "Clean room" in text


def test_notification_list_callback_does_not_collide_with_older_prefix() -> None:
    """LIST_CALLBACK_DATA (Issue: Telegram notifications) is a new
    exact-match callback and must never be a prefix of an older-page one.
    """
    assert not LIST_CALLBACK_DATA.startswith(OLDER_CALLBACK_PREFIX)
    assert not OLDER_CALLBACK_PREFIX.startswith(LIST_CALLBACK_DATA)
