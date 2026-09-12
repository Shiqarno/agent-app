import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session
from telegram import InlineKeyboardMarkup
from telegram.error import TelegramError

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
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.reward_operations import request_reward_redemption
from app.task_operations import TaskAlreadyOpenForChildError, assign_task
from app.telegram import notifications
from app.telegram.handlers.adult_tasks import _finish_assign, _finish_create, _toggle_active
from app.telegram.handlers.confirmations import _confirm, _confirm_reward, _list_view
from app.telegram.handlers.rewards import _request
from app.telegram.handlers.tasks import _mark_ready, _tasks_view
from app.telegram.keyboards.confirmations import VIEW_ALL_CALLBACK_DATA
from app.telegram.keyboards.points import LIST_CALLBACK_DATA as POINTS_LIST_CALLBACK_DATA
from app.telegram.keyboards.rewards import LIST_CALLBACK_DATA as REWARDS_LIST_CALLBACK_DATA
from app.telegram.keyboards.tasks import LIST_CALLBACK_DATA as TASKS_LIST_CALLBACK_DATA
from app.telegram.keyboards.tasks import MY_TASKS_CALLBACK_DATA

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """Same rationale as the other test_telegram_*.py RealData helpers: the
    handlers under test open their own `SessionLocal()`, a genuinely
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

    def connect(self, user: User, telegram_id: int) -> None:
        self.session.add(TelegramIdentity(user_id=user.id, telegram_user_id=telegram_id))
        self.session.commit()

    def make_task(
        self,
        creator: User,
        *,
        title: str = "Clean room",
        reward_points: int = 20,
        is_active: bool = True,
    ) -> Task:
        task = Task(
            title=title, reward_points=reward_points, is_active=is_active, created_by=creator.id
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task_ids.append(task.id)
        return task

    def make_execution(
        self, task: Task, user: User, status: TaskExecutionStatus, *, reward_points: int = 20
    ) -> TaskExecution:
        execution = TaskExecution(
            task_id=task.id, user_id=user.id, status=status, reward_points=reward_points
        )
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def make_reward(
        self, creator: User, *, name: str = "Ice cream", cost_points: int = 30
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

    def request_reward(self, child: User, reward: Reward) -> RewardRedemption:
        redemption, _, _ = request_reward_redemption(self.session, child, reward.id)
        return redemption


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


SentCall = tuple[int, str, InlineKeyboardMarkup]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[SentCall]:
    """Captures every call to the low-level Telegram sender instead of
    actually hitting the network -- every notify_* function is exercised
    for real up to (and not including) the actual HTTP call.
    """
    calls: list[SentCall] = []

    def fake_send(telegram_user_id: int, text: str, keyboard: InlineKeyboardMarkup) -> None:
        calls.append((telegram_user_id, text, keyboard))

    monkeypatch.setattr(notifications, "_send", fake_send)
    return calls


class _FailingBot:
    """Stands in for a real Bot whose delivery always fails -- used to
    prove the *real*, shipped `_send`/`_send_async` protection (not a
    monkeypatch bypassing it) actually swallows the failure.
    """

    async def send_message(self, **_kwargs: object) -> None:
        raise TelegramError("simulated delivery failure")


def _callback_data(keyboard: InlineKeyboardMarkup, label: str | None = None) -> set[str]:
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None and (label is None or button.text == label)
    }


# =========================================================================================
# Adult: task awaiting confirmation
# =========================================================================================


def test_adult_notified_when_execution_reaches_awaiting_confirmation(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD, "Ваня")
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult, title="Помыть посуду")
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    _mark_ready(child_telegram_id, str(execution.id))

    assert len(sent) == 1
    telegram_user_id, text, keyboard = sent[0]
    assert telegram_user_id == adult_telegram_id
    assert "Помыть посуду" in text
    assert "Ваня" in text
    assert VIEW_ALL_CALLBACK_DATA in _callback_data(keyboard)


def test_every_connected_adult_is_notified_exactly_once(
    real: RealData, sent: list[SentCall]
) -> None:
    adult_a = real.make_user(ADULT, "Adult A")
    adult_a_telegram_id = _next_telegram_id()
    real.connect(adult_a, adult_a_telegram_id)
    adult_b = real.make_user(ADULT, "Adult B")
    adult_b_telegram_id = _next_telegram_id()
    real.connect(adult_b, adult_b_telegram_id)
    unconnected_adult = real.make_user(ADULT, "Unconnected Adult")
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult_a)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    _mark_ready(child_telegram_id, str(execution.id))

    recipients = [telegram_user_id for telegram_user_id, _, _ in sent]
    assert sorted(recipients) == sorted([adult_a_telegram_id, adult_b_telegram_id])
    assert len(recipients) == len(set(recipients))
    del unconnected_adult


def test_no_notification_when_mark_ready_is_rejected(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    real.connect(adult, _next_telegram_id())
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult)
    # Wrong status -- mark_execution_ready only accepts IN_PROGRESS.
    execution = real.make_execution(task, child, TaskExecutionStatus.ASSIGNED)

    _mark_ready(child_telegram_id, str(execution.id))

    assert sent == []


def test_no_notification_merely_from_viewing_confirmations(
    real: RealData, sent: list[SentCall]
) -> None:
    """Opening /confirmations must never itself notify anyone."""
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    real.connect(child, _next_telegram_id())
    task = real.make_task(adult)
    real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    _list_view(adult_telegram_id)

    assert sent == []


# =========================================================================================
# Adult: reward awaiting confirmation
# =========================================================================================


def test_adult_notified_when_reward_request_is_created(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD, "Ваня")
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    real.grant_points(child, 100)
    reward = real.make_reward(adult, name="Мороженое", cost_points=30)

    _request(child_telegram_id, str(reward.id))

    assert len(sent) == 1
    telegram_user_id, text, keyboard = sent[0]
    assert telegram_user_id == adult_telegram_id
    assert "Мороженое" in text
    assert "Ваня" in text
    assert "30" in text
    assert VIEW_ALL_CALLBACK_DATA in _callback_data(keyboard)


def test_no_notification_when_reward_request_is_rejected(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    real.connect(adult, _next_telegram_id())
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    # No points granted -- insufficient balance.
    reward = real.make_reward(adult, cost_points=30)

    _request(child_telegram_id, str(reward.id))

    assert sent == []


# =========================================================================================
# Child: task becomes available
# =========================================================================================


def test_connected_child_notified_when_a_new_active_task_is_created(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)

    _finish_create(adult_telegram_id, "Помыть посуду", 15)
    created = real.session.query(Task).filter_by(title="Помыть посуду").one()
    real.task_ids.append(created.id)

    assert len(sent) == 1
    telegram_user_id, notif_text, notif_keyboard = sent[0]
    assert telegram_user_id == child_telegram_id
    assert "Помыть посуду" in notif_text
    assert "15" in notif_text
    assert TASKS_LIST_CALLBACK_DATA in _callback_data(notif_keyboard)


def test_reactivating_a_task_notifies_only_children_it_is_actually_available_to(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    free_child = real.make_user(CHILD, "Free Child")
    free_child_telegram_id = _next_telegram_id()
    real.connect(free_child, free_child_telegram_id)
    busy_child = real.make_user(CHILD, "Busy Child")
    busy_child_telegram_id = _next_telegram_id()
    real.connect(busy_child, busy_child_telegram_id)
    task = real.make_task(adult, is_active=False)
    # busy_child already holds an open (directly-assigned) execution --
    # reactivating must not claim the task is "available" to them.
    assign_task(real.session, adult, task.id, busy_child)

    _toggle_active(adult_telegram_id, str(task.id), activate=True)

    recipients = [telegram_user_id for telegram_user_id, _, _ in sent]
    assert recipients == [free_child_telegram_id]


def test_deactivating_a_task_sends_no_notification(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    real.connect(child, _next_telegram_id())
    task = real.make_task(adult, is_active=True)

    _toggle_active(adult_telegram_id, str(task.id), activate=False)

    assert sent == []


def test_no_notification_merely_from_viewing_tasks(real: RealData, sent: list[SentCall]) -> None:
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    adult = real.make_user(ADULT)
    real.make_task(adult)

    _tasks_view(child_telegram_id)

    assert sent == []


# =========================================================================================
# Child: task assigned
# =========================================================================================


def test_child_notified_when_a_task_is_assigned(real: RealData, sent: list[SentCall]) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult, title="Вынести мусор", reward_points=25)

    _finish_assign(adult_telegram_id, str(task.id), str(child.id))

    assert len(sent) == 1
    telegram_user_id, text, keyboard = sent[0]
    assert telegram_user_id == child_telegram_id
    assert "Вынести мусор" in text
    assert "25" in text
    assert MY_TASKS_CALLBACK_DATA in _callback_data(keyboard)


def test_unconnected_child_receives_no_assignment_notification(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    task = real.make_task(adult)

    text, keyboard = _finish_assign(adult_telegram_id, str(task.id), str(child.id))

    assert sent == []
    session = SessionLocal()
    try:
        execution = (
            session.query(TaskExecution).filter_by(task_id=task.id, user_id=child.id).one()
        )
        assert execution.status == TaskExecutionStatus.ASSIGNED
    finally:
        session.close()


def test_failed_assignment_produces_no_notification(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    real.connect(child, _next_telegram_id())
    task = real.make_task(adult)
    # Child already has an open execution of this Task -- assign_task must
    # raise TaskAlreadyOpenForChildError, never reaching the notify call.
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    with pytest.raises(TaskAlreadyOpenForChildError):
        assign_task(real.session, adult, task.id, child)

    _finish_assign(adult_telegram_id, str(task.id), str(child.id))

    assert sent == []


# =========================================================================================
# Child: task confirmed
# =========================================================================================


def test_child_notified_when_their_task_is_confirmed(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult, title="Помыть посуду", reward_points=20)
    execution = real.make_execution(
        task, child, TaskExecutionStatus.AWAITING_CONFIRMATION, reward_points=20
    )
    # Task's reward changed since the execution snapshot was taken -- the
    # notification must use the snapshot, not this current value.
    task.reward_points = 99
    real.session.commit()

    _confirm(adult_telegram_id, str(execution.id))

    assert len(sent) == 1
    telegram_user_id, text, keyboard = sent[0]
    assert telegram_user_id == child_telegram_id
    assert "20" in text
    assert "99" not in text
    assert POINTS_LIST_CALLBACK_DATA in _callback_data(keyboard)


def test_confirm_notification_failure_does_not_affect_task_completion_or_points(
    real: RealData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "_get_bot", lambda: _FailingBot())
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    real.connect(child, _next_telegram_id())
    task = real.make_task(adult)
    execution = real.make_execution(
        task, child, TaskExecutionStatus.AWAITING_CONFIRMATION, reward_points=20
    )

    toast, _text, _keyboard = _confirm(adult_telegram_id, str(execution.id))

    assert "подтверждена" in toast
    session = SessionLocal()
    try:
        refreshed = session.get(TaskExecution, execution.id)
        assert refreshed is not None
        assert refreshed.status == TaskExecutionStatus.COMPLETED
        transaction = (
            session.query(PointTransaction)
            .filter_by(task_execution_id=execution.id, reason=PointTransactionReason.TASK_COMPLETED)
            .one()
        )
        assert transaction.amount == 20
    finally:
        session.close()


# =========================================================================================
# Child: reward confirmed
# =========================================================================================


def test_child_notified_when_their_reward_request_is_confirmed(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    real.grant_points(child, 100)
    reward = real.make_reward(adult, name="Мороженое", cost_points=30)
    redemption = real.request_reward(child, reward)
    # Cost changed since the request snapshot was taken -- the notification
    # must use the redemption's own frozen snapshot.
    reward.cost_points = 999
    real.session.commit()

    _confirm_reward(adult_telegram_id, str(redemption.id))

    assert len(sent) == 1
    telegram_user_id, text, keyboard = sent[0]
    assert telegram_user_id == child_telegram_id
    assert "Мороженое" in text
    assert "30" in text
    assert "999" not in text
    assert REWARDS_LIST_CALLBACK_DATA in _callback_data(keyboard)


def test_confirm_reward_notification_failure_does_not_affect_redemption_or_points(
    real: RealData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications, "_get_bot", lambda: _FailingBot())
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)
    real.connect(child, _next_telegram_id())
    real.grant_points(child, 100)
    reward = real.make_reward(adult, cost_points=30)
    redemption = real.request_reward(child, reward)

    toast, _text, _keyboard = _confirm_reward(adult_telegram_id, str(redemption.id))

    assert "подтверждена" in toast
    session = SessionLocal()
    try:
        refreshed = session.get(RewardRedemption, redemption.id)
        assert refreshed is not None
        assert refreshed.status == RewardRedemptionStatus.CONFIRMED
        transaction = (
            session.query(PointTransaction)
            .filter_by(redemption_id=redemption.id, reason=PointTransactionReason.REWARD_REDEEMED)
            .one()
        )
        assert transaction.amount == -30
    finally:
        session.close()


# =========================================================================================
# Connectivity: no Telegram connection never blocks the business operation
# =========================================================================================


def test_task_awaiting_confirmation_succeeds_without_any_connected_adult(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)  # not connected
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    _mark_ready(child_telegram_id, str(execution.id))

    assert sent == []
    session = SessionLocal()
    try:
        refreshed = session.get(TaskExecution, execution.id)
        assert refreshed is not None
        assert refreshed.status == TaskExecutionStatus.AWAITING_CONFIRMATION
    finally:
        session.close()


def test_reward_awaiting_confirmation_succeeds_without_any_connected_adult(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)  # not connected
    child = real.make_user(CHILD)
    child_telegram_id = _next_telegram_id()
    real.connect(child, child_telegram_id)
    real.grant_points(child, 100)
    reward = real.make_reward(adult, cost_points=30)

    toast, success, _text, _keyboard = _request(child_telegram_id, str(reward.id))

    assert success is True
    assert sent == []


def test_task_available_succeeds_with_no_connected_children(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    real.make_user(CHILD)  # not connected

    text, _keyboard = _finish_create(adult_telegram_id, "Clean room", 10)
    created = real.session.query(Task).filter_by(title="Clean room").one()
    real.task_ids.append(created.id)

    assert sent == []
    assert "Clean room" in text


def test_task_assignment_succeeds_for_an_unconnected_child(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)  # not connected
    task = real.make_task(adult)

    text, _keyboard = _finish_assign(adult_telegram_id, str(task.id), str(child.id))

    assert sent == []
    assert child.name in text


def test_task_confirmation_succeeds_for_an_unconnected_child(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)  # not connected
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, _text, _keyboard = _confirm(adult_telegram_id, str(execution.id))

    assert sent == []
    assert "подтверждена" in toast


def test_reward_confirmation_succeeds_for_an_unconnected_child(
    real: RealData, sent: list[SentCall]
) -> None:
    adult = real.make_user(ADULT)
    adult_telegram_id = _next_telegram_id()
    real.connect(adult, adult_telegram_id)
    child = real.make_user(CHILD)  # not connected
    real.grant_points(child, 100)
    reward = real.make_reward(adult, cost_points=30)
    redemption = real.request_reward(child, reward)

    toast, _text, _keyboard = _confirm_reward(adult_telegram_id, str(redemption.id))

    assert sent == []
    assert "подтверждена" in toast
