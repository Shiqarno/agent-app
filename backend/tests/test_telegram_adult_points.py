import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

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
from app.points_operations import PAGE_SIZE, PointsView
from app.telegram.handlers.adult_points import (
    _CHILD_NOT_FOUND_TEXT,
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _adjust_menu_view,
    _child_points_view,
    _children_list_view,
    _finish_adjust,
    _points_command_view,
    _route_flow_text,
    _start_adjust,
)
from app.telegram.keyboards.adult_points import (
    ADD_CALLBACK_PREFIX,
    ADJUST_CALLBACK_PREFIX,
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    REMOVE_CALLBACK_PREFIX,
    child_points_keyboard,
    decode_uuid,
)
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
        self.execution_ids: list[uuid.UUID] = []

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    def connect_via_activation(self, user: User, telegram_id: int) -> None:
        token = insert_activation(self.session, user.id)
        self.session.commit()
        activate_telegram_identity(self.session, token, telegram_id)

    def seed_balance(self, user: User, amount: int, *, title: str = "Seed task") -> None:
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
        self.execution_ids.append(execution.id)

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
        if data.user_ids:
            session.query(PointTransaction).filter(
                PointTransaction.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
        if data.execution_ids:
            session.query(TaskExecution).filter(TaskExecution.id.in_(data.execution_ids)).delete(
                synchronize_session=False
            )
        if data.task_ids:
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
# Points list
# =========================================================================================


def test_adult_can_open_points_list_with_child_balances(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 150)

    text, keyboard = _children_list_view(telegram_id)

    assert "Alex" in text
    assert "150" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Alex" in label for label in labels)
    assert any("Home" in label for label in labels)


def test_adult_users_do_not_appear_in_the_points_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    other_adult = real.make_user(ADULT, "Other Adult")

    text, keyboard = _children_list_view(telegram_id)

    assert other_adult.name not in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any(other_adult.name in label for label in labels)


def test_child_cannot_open_the_adult_points_list(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, keyboard = _children_list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_unconnected_account_cannot_open_the_points_list() -> None:
    text, keyboard = _children_list_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Child Points details
# =========================================================================================


def test_adult_can_open_a_childs_points_details(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 200, title="Clean room")

    text, keyboard = _child_points_view(telegram_id, str(child.id), None)

    assert "Alex" in text
    assert "200" in text
    assert "Clean room" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Adjust points" in label for label in labels)
    assert any("Back" in label for label in labels)
    assert not any("Older" in label for label in labels)


def test_older_pagination_shows_older_history_for_a_child(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    for index in range(PAGE_SIZE + 1):
        real.seed_balance(child, 1, title=f"Task {index}")

    first_page_text, first_keyboard = _child_points_view(telegram_id, str(child.id), None)
    assert first_keyboard is not None
    labels = [button.text for row in first_keyboard.inline_keyboard for button in row]
    older_buttons = [
        button for row in first_keyboard.inline_keyboard for button in row if button.text == "Older"
    ]
    assert any("Older" in label for label in labels)
    assert len(older_buttons) == 1
    encoded_cursor = older_buttons[0].callback_data.rsplit(":", 1)[1]  # type: ignore[union-attr]
    cursor = decode_uuid(encoded_cursor)
    assert cursor is not None

    second_page_text, _ = _child_points_view(telegram_id, str(child.id), cursor)

    assert first_page_text != second_page_text


def test_older_callback_data_fits_within_telegrams_64_byte_limit() -> None:
    """Regression for the `Button_data_invalid` bug: `child_points_keyboard()`
    used to embed both the Child's UUID and the pagination cursor's UUID in
    their full 36-char hyphenated form, so the `Older` button's callback_data
    exceeded Telegram's 64-byte `callback_data` limit and Telegram rejected
    the whole keyboard on `edit_message_text()`. Must check *encoded bytes*,
    not `len(str)` -- the limit is byte-based and the payload is UTF-8.
    """
    child_id = uuid.uuid4()
    view = PointsView(balance=10, transactions=[], next_cursor=uuid.uuid4())

    keyboard = child_points_keyboard(child_id, view)

    for row in keyboard.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_older_callback_data_round_trips_to_the_correct_child_and_cursor() -> None:
    child_id = uuid.uuid4()
    cursor = uuid.uuid4()
    view = PointsView(balance=10, transactions=[], next_cursor=cursor)

    keyboard = child_points_keyboard(child_id, view)

    older_button = next(
        button for row in keyboard.inline_keyboard for button in row if button.text == "Older"
    )
    assert older_button.callback_data is not None
    payload = older_button.callback_data.removeprefix(OLDER_CALLBACK_PREFIX)
    raw_child_token, _, raw_cursor_token = payload.partition(":")

    assert decode_uuid(raw_child_token) == child_id
    assert decode_uuid(raw_cursor_token) == cursor


def test_decode_uuid_rejects_malformed_or_empty_input() -> None:
    assert decode_uuid("") is None
    assert decode_uuid("not-a-valid-token") is None


def test_older_pagination_with_undecodable_child_token_shows_child_not_found(
    real: RealData,
) -> None:
    """Mirrors handle_older_child_points falling back to an empty child
    segment when a crafted/corrupted callback's child token fails to decode
    -- the Adult must land on a safe "Child not found" screen, never a crash.
    """
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, keyboard = _child_points_view(telegram_id, "", None)

    assert text == _CHILD_NOT_FOUND_TEXT
    assert keyboard is not None


def test_crafted_callback_cannot_open_an_adults_points_via_the_child_details_screen(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    other_adult = real.make_user(ADULT, "Other Adult")

    text, keyboard = _child_points_view(telegram_id, str(other_adult.id), None)

    assert text == _CHILD_NOT_FOUND_TEXT
    assert keyboard is not None


def test_child_cannot_open_the_child_details_screen(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)
    other_child = real.make_user(CHILD, "Other Child")

    text, keyboard = _child_points_view(telegram_id, str(other_child.id), None)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Adjust menu
# =========================================================================================


def test_adjust_menu_shows_the_current_balance(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 75)

    text, keyboard = _adjust_menu_view(telegram_id, str(child.id))

    assert "75" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Add points" in label for label in labels)
    assert any("Remove points" in label for label in labels)


# =========================================================================================
# Add flow
# =========================================================================================


def test_starting_add_prompts_for_an_amount(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")

    text, should_start, keyboard = _start_adjust(telegram_id, str(child.id), "add")

    assert should_start is True
    assert "Alex" in text
    assert keyboard is None


def test_child_actor_cannot_start_the_add_flow(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)
    other_child = real.make_user(CHILD, "Other Child")

    text, should_start, _ = _start_adjust(telegram_id, str(other_child.id), "add")

    assert should_start is False
    assert text == _NOT_AN_ADULT_TEXT


def test_invalid_amount_is_rejected_and_flow_stays_open(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    flow = {"direction": "add", "step": "amount", "child_id": str(child.id)}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "not a number")

    assert finished is False
    assert keyboard is None
    assert flow["step"] == "amount"


def test_zero_amount_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    flow = {"direction": "add", "step": "amount", "child_id": str(child.id)}

    text, _, finished = _route_flow_text(telegram_id, flow, "0")

    assert finished is False
    assert flow["step"] == "amount"


def test_valid_amount_advances_to_description_step(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    flow = {"direction": "add", "step": "amount", "child_id": str(child.id)}

    text, _, finished = _route_flow_text(telegram_id, flow, "100")

    assert finished is False
    assert flow["step"] == "description"
    assert flow["magnitude"] == 100


def test_empty_description_is_rejected_and_flow_stays_open(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    flow = {"direction": "add", "step": "description", "child_id": str(child.id), "magnitude": 100}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "   ")

    assert finished is False
    assert flow["step"] == "description"


def test_successful_add_creates_a_manual_adjustment_and_shows_new_balance(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 50)
    flow = {"direction": "add", "step": "description", "child_id": str(child.id), "magnitude": 100}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "Bonus for helping with dinner")

    assert finished is True
    assert "150" in text
    session = SessionLocal()
    try:
        transaction = (
            session.query(PointTransaction)
            .filter_by(user_id=child.id, reason=PointTransactionReason.MANUAL_ADJUSTMENT)
            .one()
        )
        assert transaction.amount == 100
        assert transaction.description == "Bonus for helping with dinner"
    finally:
        session.close()


# =========================================================================================
# Remove flow
# =========================================================================================


def test_starting_remove_prompts_for_an_amount(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")

    text, should_start, keyboard = _start_adjust(telegram_id, str(child.id), "remove")

    assert should_start is True
    assert "Alex" in text


def test_insufficient_balance_is_rejected_during_remove(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 50)

    text, keyboard = _finish_adjust(telegram_id, str(child.id), "remove", 100, "Too much")

    assert "cannot remove" in text.lower()
    assert keyboard is not None
    session = SessionLocal()
    try:
        count = (
            session.query(PointTransaction)
            .filter_by(user_id=child.id, reason=PointTransactionReason.MANUAL_ADJUSTMENT)
            .count()
        )
        assert count == 0
    finally:
        session.close()


def test_successful_remove_creates_a_manual_adjustment_and_shows_new_balance(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 100)

    text, keyboard = _finish_adjust(
        telegram_id, str(child.id), "remove", 40, "Penalty for breaking the rule"
    )

    assert "60" in text
    session = SessionLocal()
    try:
        transaction = (
            session.query(PointTransaction)
            .filter_by(user_id=child.id, reason=PointTransactionReason.MANUAL_ADJUSTMENT)
            .one()
        )
        assert transaction.amount == -40
        assert transaction.description == "Penalty for breaking the rule"
    finally:
        session.close()


# =========================================================================================
# Authorization / crafted callbacks
# =========================================================================================


def test_crafted_callback_cannot_adjust_an_adults_points(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    other_adult = real.make_user(ADULT, "Other Adult")

    text, keyboard = _finish_adjust(telegram_id, str(other_adult.id), "add", 100, "Nice try")

    assert text == _CHILD_NOT_FOUND_TEXT
    session = SessionLocal()
    try:
        count = (
            session.query(PointTransaction)
            .filter_by(user_id=other_adult.id, reason=PointTransactionReason.MANUAL_ADJUSTMENT)
            .count()
        )
        assert count == 0
    finally:
        session.close()


def test_child_cannot_finish_an_adjustment_even_with_a_crafted_call(real: RealData) -> None:
    """Defense in depth: even if a Child somehow reached _finish_adjust
    directly (bypassing the role-gated _start_adjust), the Application
    layer's own authorization still refuses it.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)
    other_child = real.make_user(CHILD, "Other Child")

    text, _ = _finish_adjust(telegram_id, str(other_child.id), "add", 100, "Nice try")

    assert text == _NOT_AN_ADULT_TEXT
    session = SessionLocal()
    try:
        count = (
            session.query(PointTransaction)
            .filter_by(user_id=other_child.id, reason=PointTransactionReason.MANUAL_ADJUSTMENT)
            .count()
        )
        assert count == 0
    finally:
        session.close()


# =========================================================================================
# Regression: Child /points must be unaffected
# =========================================================================================


def test_child_points_command_still_shows_the_child_self_service_view(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)
    real.seed_balance(child, 30, title="Clean room")

    text, keyboard = _points_command_view(telegram_id)

    assert "Balance" in text
    assert "30" in text
    assert "Clean room" in text


def test_adult_points_command_shows_the_children_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    child = real.make_user(CHILD, "Alex")
    real.seed_balance(child, 10)

    text, keyboard = _points_command_view(telegram_id)

    assert "Alex" in text
    assert keyboard is not None


# =========================================================================================
# Callback payload sanity
# =========================================================================================


def test_callback_prefixes_do_not_collide() -> None:
    sample_id = "12345678-1234-1234-1234-123456789012"
    prefixes = {
        "open": OPEN_CALLBACK_PREFIX,
        "older": OLDER_CALLBACK_PREFIX,
        "adjust": ADJUST_CALLBACK_PREFIX,
        "add": ADD_CALLBACK_PREFIX,
        "remove": REMOVE_CALLBACK_PREFIX,
    }
    for name, prefix in prefixes.items():
        payload = f"{prefix}{sample_id}"
        for other_name, other_prefix in prefixes.items():
            if other_name == name:
                continue
            assert not payload.startswith(other_prefix), (
                f"{name} payload collides with {other_name}"
            )
