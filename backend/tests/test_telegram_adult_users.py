import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.activation import resolve_activation
from app.db import SessionLocal
from app.models import TelegramIdentity, User, UserActivation, UserRole
from app.telegram.handlers.adult_tasks import _FLOW_KEY as TASK_FLOW_KEY
from app.telegram.handlers.adult_users import (
    _FLOW_KEY,
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _USER_NOT_FOUND_TEXT,
    _build_activation_link,
    _finish_add_child,
    _finish_get_link,
    _route_flow_text,
    _start_add_child,
    _user_details_view,
    _users_list_view,
)
from app.telegram.keyboards.users import GET_LINK_CALLBACK_PREFIX, OPEN_CALLBACK_PREFIX
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD

_BOT_USERNAME = "test_family_bot"


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

    def make_child_with_activation(self, name: str = "Alex") -> User:
        child = self.make_user(CHILD, name)
        insert_activation(self.session, child.id)
        self.session.commit()
        return child

    def connect(self, target: User, telegram_id: int) -> None:
        self.session.add(TelegramIdentity(user_id=target.id, telegram_user_id=telegram_id))
        self.session.commit()

    def connect_via_activation(self, user: User, telegram_id: int) -> None:
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
# Users list
# =========================================================================================


def test_adult_can_open_users(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    real.make_child_with_activation("Alex")

    text, keyboard = _users_list_view(telegram_id)

    assert "Users" in text
    assert "Alex" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Alex" in label for label in labels)
    assert any("Add Child" in label for label in labels)
    assert any("Home" in label for label in labels)


def test_child_cannot_access_users(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, keyboard = _users_list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_users_list_renders_connection_status(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    connected_child = real.make_child_with_activation("Connected Kid")
    real.connect(connected_child, _next_telegram_id())
    real.make_child_with_activation("Pending Kid")

    text, _keyboard = _users_list_view(telegram_id)

    assert "Connected Kid\nChild\nConnected" in text
    assert "Pending Kid\nChild\nNot connected" in text


def test_users_view_for_unconnected_account() -> None:
    text, keyboard = _users_list_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# User Details / activation-link eligibility
# =========================================================================================


def test_unconnected_child_exposes_activation_action(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_child_with_activation("Alex")

    text, keyboard = _user_details_view(telegram_id, str(child.id))

    assert "Alex" in text
    assert "Not connected" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Get activation link" in label for label in labels)


def test_connected_child_does_not_expose_activation_action(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_child_with_activation("Alex")
    real.connect(child, _next_telegram_id())

    text, keyboard = _user_details_view(telegram_id, str(child.id))

    assert "Connected" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any("Get activation link" in label for label in labels)


def test_open_nonexistent_user_does_not_strand_the_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, keyboard = _user_details_view(telegram_id, str(uuid.uuid4()))

    assert text == _USER_NOT_FOUND_TEXT
    assert keyboard is not None


def test_child_cannot_open_user_details_via_crafted_callback(real: RealData) -> None:
    child_actor = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child_actor, telegram_id)
    other_child = real.make_child_with_activation("Alex")

    text, keyboard = _user_details_view(telegram_id, str(other_child.id))

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Add Child
# =========================================================================================


def test_start_add_child_prompts_for_a_name(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, should_start = _start_add_child(telegram_id)

    assert should_start is True
    assert "name" in text.lower()


def test_child_cannot_start_add_child(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, should_start = _start_add_child(telegram_id)

    assert should_start is False
    assert text == _NOT_AN_ADULT_TEXT


def test_add_child_flow_end_to_end_displays_the_activation_link(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    flow: dict[str, object] = {"action": "add_child"}
    text, keyboard, finished = _route_flow_text(telegram_id, flow, "Alex", _BOT_USERNAME)

    assert finished is True
    assert "Alex was created." in text
    assert f"https://t.me/{_BOT_USERNAME}?start=" in text
    assert "72 hours" in text
    assert keyboard is not None

    created = real.session.query(User).filter_by(name="Alex").one()
    real.user_ids.append(created.id)
    assert created.role == CHILD


def test_created_child_activation_link_token_is_usable(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, _keyboard = _finish_add_child(telegram_id, "Alex", _BOT_USERNAME)

    link_line = next(line for line in text.splitlines() if line.startswith("https://t.me/"))
    token = link_line.removeprefix(f"https://t.me/{_BOT_USERNAME}?start=")
    _activation, resolved_user = resolve_activation(real.session, token)
    real.user_ids.append(resolved_user.id)
    assert resolved_user.name == "Alex"


def test_add_child_rejects_a_blank_name(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    flow: dict[str, object] = {"action": "add_child"}
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "   ", _BOT_USERNAME)

    assert finished is False
    assert "name" in text.lower()


def test_add_child_via_crafted_flow_state_rejects_a_child_actor(real: RealData) -> None:
    """Even if a Child somehow had `adult_user_flow` state, the Application
    layer must still refuse the creation.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, _keyboard = _finish_add_child(telegram_id, "Hacked", _BOT_USERNAME)

    assert text == _NOT_AN_ADULT_TEXT
    assert real.session.query(User).filter_by(name="Hacked").count() == 0


# =========================================================================================
# Generate activation link for an existing Child
# =========================================================================================


def test_generate_activation_link_for_an_unconnected_child(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_child_with_activation("Alex")

    text, keyboard = _finish_get_link(telegram_id, str(child.id), _BOT_USERNAME)

    assert f"https://t.me/{_BOT_USERNAME}?start=" in text
    assert "72 hours" in text
    assert keyboard is not None


def test_generate_activation_link_rejects_a_connected_child(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_child_with_activation("Alex")
    real.connect(child, _next_telegram_id())

    text, keyboard = _finish_get_link(telegram_id, str(child.id), _BOT_USERNAME)

    assert "already connected" in text.lower()
    assert keyboard is not None


def test_generate_activation_link_child_cannot_bypass_via_crafted_callback(
    real: RealData,
) -> None:
    child_actor = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child_actor, telegram_id)
    target_child = real.make_child_with_activation("Alex")

    text, _keyboard = _finish_get_link(telegram_id, str(target_child.id), _BOT_USERNAME)

    assert text == _NOT_AN_ADULT_TEXT


def test_generate_activation_link_for_a_nonexistent_user_does_not_strand_the_adult(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, keyboard = _finish_get_link(telegram_id, str(uuid.uuid4()), _BOT_USERNAME)

    assert text == _USER_NOT_FOUND_TEXT
    assert keyboard is not None


def test_activation_link_construction_uses_the_bots_own_username() -> None:
    link = _build_activation_link("my_family_bot", "raw-token-value")

    assert link == "https://t.me/my_family_bot?start=raw-token-value"


# =========================================================================================
# Callback payload sanity
# =========================================================================================


def test_open_and_get_link_callback_prefixes_do_not_collide() -> None:
    assert not "adultuser:getlink:123".startswith(OPEN_CALLBACK_PREFIX)
    assert not "adultuser:open:123".startswith(GET_LINK_CALLBACK_PREFIX)


def test_flow_key_is_distinct_from_the_adult_task_flow_key() -> None:
    assert _FLOW_KEY != TASK_FLOW_KEY
