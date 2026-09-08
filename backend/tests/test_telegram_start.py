import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session
from telegram import BotCommandScopeChat

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import TelegramIdentity, User, UserActivation, UserRole
from app.telegram.commands import ADULT_COMMANDS, CHILD_COMMANDS
from app.telegram.handlers.start import _activate, _resolve_home, handle_start
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
