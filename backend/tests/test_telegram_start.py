import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session
from telegram import BotCommandScopeChat

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.commands import ADULT_COMMANDS, CHILD_COMMANDS
from app.telegram.handlers.confirmations import _list_view as _confirmation_list_view
from app.telegram.handlers.start import _activate, _resolve_home, handle_start
from app.telegram.views.confirmations import CONFIRMATIONS_HEADING, NO_CONFIRMATIONS_TEXT
from app.telegram_identity import activate_telegram_identity

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

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    def connect(self, user: User, telegram_id: int) -> None:
        token = insert_activation(self.session, user.id)
        self.session.commit()
        activate_telegram_identity(self.session, token, telegram_id)

    def make_task(
        self, creator: User, *, title: str = "Clean room", reward_points: int = 20
    ) -> Task:
        task = Task(title=title, reward_points=reward_points, created_by=creator.id)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task_ids.append(task.id)
        return task

    def make_execution(self, task: Task, user: User, status: TaskExecutionStatus) -> TaskExecution:
        execution = TaskExecution(
            task_id=task.id, user_id=user.id, status=status, reward_points=task.reward_points
        )
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)
        return execution

    def grant_points(self, user: User, amount: int) -> None:
        task = self.make_task(user, title="Balance seed", reward_points=amount)
        execution = self.make_execution(task, user, TaskExecutionStatus.COMPLETED)
        self.session.add(
            PointTransaction(
                user_id=user.id,
                task_execution_id=execution.id,
                amount=amount,
                reason=PointTransactionReason.TASK_COMPLETED,
            )
        )
        self.session.commit()


@pytest.fixture
def real(db_session: Session) -> Iterator[RealData]:
    del db_session
    session = SessionLocal()
    data = RealData(session)
    try:
        yield data
    finally:
        session.rollback()
        if data.task_ids:
            session.query(PointTransaction).filter(
                PointTransaction.task_execution_id.in_(
                    session.query(TaskExecution.id).filter(TaskExecution.task_id.in_(data.task_ids))
                )
            ).delete(synchronize_session=False)
            session.query(TaskExecution).filter(TaskExecution.task_id.in_(data.task_ids)).delete(
                synchronize_session=False
            )
            session.query(Task).filter(Task.id.in_(data.task_ids)).delete(synchronize_session=False)
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
# _activate / _resolve_home: role returned for command-panel setup (Issue #35)
# =========================================================================================


def test_activate_returns_the_users_role_on_success(real: RealData) -> None:
    child = real.make_user(CHILD)
    token = insert_activation(real.session, child.id)
    real.session.commit()

    _message, role = _activate(token, _next_telegram_id())

    assert role == CHILD


def test_activate_returns_no_role_on_an_invalid_token() -> None:
    _message, role = _activate("not-a-real-token", _next_telegram_id())

    assert role is None


def test_resolve_home_returns_the_childs_role(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    _text, _keyboard, role = _resolve_home(telegram_id)

    assert role == CHILD


def test_resolve_home_returns_the_adults_role(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    _text, _keyboard, role = _resolve_home(telegram_id)

    assert role == ADULT


def test_resolve_home_returns_no_role_when_unconnected() -> None:
    _text, _keyboard, role = _resolve_home(_next_telegram_id())

    assert role is None


# =========================================================================================
# Issue #36: Child Home shows the current Points balance
# =========================================================================================


def test_resolve_home_shows_the_childs_current_points_balance(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 120)

    text, _keyboard, _role = _resolve_home(telegram_id)

    assert "Твои баллы: 💰 120" in text


def test_resolve_home_balance_reflects_the_point_ledger_not_a_stored_value(
    real: RealData,
) -> None:
    """Issue #36: no separate stored balance -- granting more points changes
    what Home shows, because it's read fresh from the ledger every time.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.grant_points(child, 50)
    real.grant_points(child, 30)

    text, _keyboard, _role = _resolve_home(telegram_id)

    assert "Твои баллы: 💰 80" in text


def test_resolve_home_shows_zero_balance_for_a_child_with_no_transactions(
    real: RealData,
) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, _keyboard, _role = _resolve_home(telegram_id)

    assert "Твои баллы: 💰 0" in text


def test_resolve_home_still_shows_existing_child_navigation_hints(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, _keyboard, _role = _resolve_home(telegram_id)

    assert "/tasks" in text
    assert "/mytasks" in text
    assert "/rewards" in text
    assert "/points" in text


# =========================================================================================
# Issue #36: Adult Home reuses the Confirmations list directly
# =========================================================================================


def test_resolve_home_for_adult_matches_the_confirmations_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room")
    real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    home_text, home_keyboard, role = _resolve_home(telegram_id)
    list_text, list_keyboard = _confirmation_list_view(telegram_id)

    assert role == ADULT
    assert home_text == list_text == CONFIRMATIONS_HEADING
    assert home_keyboard is not None
    assert list_keyboard is not None
    home_callbacks = [b.callback_data for row in home_keyboard.inline_keyboard for b in row]
    list_callbacks = [b.callback_data for row in list_keyboard.inline_keyboard for b in row]
    assert home_callbacks == list_callbacks
    home_labels = [b.text for row in home_keyboard.inline_keyboard for b in row]
    assert home_labels == ["Clean room · Alex"]


def test_resolve_home_for_adult_uses_the_confirmations_empty_state(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard, role = _resolve_home(telegram_id)

    assert role == ADULT
    assert text == f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_resolve_home_does_not_confirm_or_return_anything(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    _resolve_home(telegram_id)

    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.AWAITING_CONFIRMATION


# =========================================================================================
# handle_start: native command-menu registration (Issue #35)
# =========================================================================================


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, object]] = []

    async def reply_text(self, text: str, reply_markup: object = None) -> None:
        self.replies.append((text, reply_markup))


class _FakeTelegramUser:
    def __init__(self, telegram_user_id: int) -> None:
        self.id = telegram_user_id


class _FakeUpdate:
    def __init__(self, telegram_user_id: int) -> None:
        self.effective_user = _FakeTelegramUser(telegram_user_id)
        self.message = _FakeMessage()


class _FakeBot:
    def __init__(self) -> None:
        self.set_my_commands_calls: list[tuple[Any, Any]] = []

    async def set_my_commands(self, commands: Any, scope: Any = None) -> None:
        self.set_my_commands_calls.append((commands, scope))


class _FakeContext:
    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or []
        self.bot = _FakeBot()


def test_handle_start_sets_the_child_command_menu_for_a_connected_child(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    update = _FakeUpdate(telegram_id)
    context = _FakeContext()

    asyncio.run(handle_start(update, context))  # type: ignore[arg-type]

    assert len(context.bot.set_my_commands_calls) == 1
    commands, scope = context.bot.set_my_commands_calls[0]
    assert commands == CHILD_COMMANDS
    assert isinstance(scope, BotCommandScopeChat)
    assert scope.chat_id == telegram_id


def test_handle_start_sets_the_adult_command_menu_for_a_connected_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    update = _FakeUpdate(telegram_id)
    context = _FakeContext()

    asyncio.run(handle_start(update, context))  # type: ignore[arg-type]

    assert len(context.bot.set_my_commands_calls) == 1
    commands, scope = context.bot.set_my_commands_calls[0]
    assert commands == ADULT_COMMANDS
    assert isinstance(scope, BotCommandScopeChat)
    assert scope.chat_id == telegram_id


def test_handle_start_does_not_set_a_command_menu_for_an_unconnected_account() -> None:
    telegram_id = _next_telegram_id()
    update = _FakeUpdate(telegram_id)
    context = _FakeContext()

    asyncio.run(handle_start(update, context))  # type: ignore[arg-type]

    assert context.bot.set_my_commands_calls == []


def test_handle_start_sets_the_command_menu_on_successful_activation(real: RealData) -> None:
    child = real.make_user(CHILD)
    token = insert_activation(real.session, child.id)
    real.session.commit()
    telegram_id = _next_telegram_id()
    update = _FakeUpdate(telegram_id)
    context = _FakeContext(args=[token])

    asyncio.run(handle_start(update, context))  # type: ignore[arg-type]

    assert len(context.bot.set_my_commands_calls) == 1
    commands, scope = context.bot.set_my_commands_calls[0]
    assert commands == CHILD_COMMANDS
    assert scope.chat_id == telegram_id


def test_handle_start_does_not_set_a_command_menu_on_failed_activation() -> None:
    telegram_id = _next_telegram_id()
    update = _FakeUpdate(telegram_id)
    context = _FakeContext(args=["not-a-real-token"])

    asyncio.run(handle_start(update, context))  # type: ignore[arg-type]

    assert context.bot.set_my_commands_calls == []
