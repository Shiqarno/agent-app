import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import (
    Task,
    TaskExecution,
    TaskExecutionStatus,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.handlers.adult_tasks import (
    _ALREADY_OPEN_TEXT,
    _CHILD_NOT_FOUND_TEXT,
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _TASK_NOT_EDITABLE_TEXT,
    _TASK_NOT_FOUND_TEXT,
    _adult_tasks_list_view,
    _assign_menu_view,
    _finish_assign,
    _finish_create,
    _finish_edit_reward,
    _finish_edit_title,
    _route_flow_text,
    _start_create,
    _start_edit_field,
    _start_edit_menu,
    _task_details_view,
    _tasks_command_view,
    _toggle_active,
)
from app.telegram.keyboards.adult_points import decode_uuid
from app.telegram.keyboards.adult_tasks import (
    ACTIVATE_CALLBACK_PREFIX,
    ASSIGN_CALLBACK_PREFIX,
    ASSIGN_TO_CALLBACK_PREFIX,
    DEACTIVATE_CALLBACK_PREFIX,
    EDIT_CALLBACK_PREFIX,
    LIST_CALLBACK_DATA,
    OPEN_CALLBACK_PREFIX,
    assign_children_keyboard,
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

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

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

    def make_execution(self, task: Task, user: User, status: TaskExecutionStatus) -> TaskExecution:
        execution = TaskExecution(
            task_id=task.id, user_id=user.id, status=status, reward_points=task.reward_points
        )
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)
        return execution

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
        if data.task_ids:
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
# /tasks dispatch and rendering
# =========================================================================================


def test_adult_tasks_command_opens_adult_tasks_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)

    text, keyboard = _tasks_command_view(telegram_id)

    # Issue #36: the heading is the ENTIRE message text -- name, reward,
    # and availability all live only on the button, never duplicated as
    # text above it.
    assert text == "Все задачи"
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Clean room" in label for label in labels)
    assert any("Добавить задачу" in label for label in labels)
    assert any("Домой" in label for label in labels)
    assert keyboard.inline_keyboard[0][0].callback_data == f"{OPEN_CALLBACK_PREFIX}{task.id}"
    # No "Available"/"Unavailable" word on the button -- an active Task's
    # name is shown plain.
    label = keyboard.inline_keyboard[0][0].text
    assert label == "Clean room · 💰 20"
    assert "❌" not in label
    assert "̶" not in label
    assert "pts" not in label


def test_adult_tasks_list_button_is_not_struck_through_for_an_active_task_with_an_open_execution(
    real: RealData,
) -> None:
    """Issue #36: the button's visual state is driven by `Task.is_active`
    alone, never by whether a current execution exists -- a directly-
    assigned Task (Issue #32) can be active with an open execution, and
    must still show plain (no strikethrough), matching `is_active`'s own
    established, execution-independent meaning.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20, is_active=True)
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    _text, keyboard = _tasks_command_view(telegram_id)

    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "Clean room · 💰 20"


def test_adult_tasks_list_button_marks_an_inactive_tasks_name_with_a_cross(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20, is_active=False)

    _text, keyboard = _tasks_command_view(telegram_id)

    assert keyboard is not None
    button = keyboard.inline_keyboard[0][0]
    label = button.text
    # Issue #38: an inactive Task's button shows a `❌` prefix and its
    # plain (unformatted) name -- no reward at all, since the button
    # represents an unavailable self-claim offer, not a reward-bearing
    # action.
    assert label == "❌ Clean room"
    assert "20" not in label
    assert "💰" not in label
    assert "pts" not in label
    assert "Available" not in label
    assert "Unavailable" not in label
    # No strikethrough combining marks -- the name is completely plain.
    assert "̶" not in label
    # The label change must not affect the underlying callback identifier.
    assert button.callback_data == f"{OPEN_CALLBACK_PREFIX}{task.id}"


def test_adult_tasks_list_button_marks_a_multi_word_inactive_tasks_name_with_a_cross(
    real: RealData,
) -> None:
    """Issue #38: explicitly verifies a multi-word name end to end through
    the actual list rendering, not just in isolation.
    """
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.make_task(adult, title="Помыть пол", reward_points=20, is_active=False)

    _text, keyboard = _tasks_command_view(telegram_id)

    assert keyboard is not None
    label = keyboard.inline_keyboard[0][0].text
    assert label == "❌ Помыть пол"
    assert "̶" not in label


def test_child_tasks_command_still_opens_child_tasks(real: RealData) -> None:
    """Regression: /tasks must remain the existing Child Available-Tasks
    screen for a Child, unaffected by the new Adult dispatch.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.make_task(child, title="Clean room")

    text, keyboard = _tasks_command_view(telegram_id)

    assert "Take" not in text  # Child view has no "Take" in the text itself
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    # Issue #36: Child /tasks buttons no longer say "Take" either.
    assert any("Clean room" in label for label in labels)
    assert not any(label.startswith("Take") for label in labels)


def test_unavailable_task_shows_current_execution_on_details_not_the_list(
    real: RealData,
) -> None:
    """Issue #36: the list itself carries no per-task execution context any
    more (only the button's `❌` marker reflects `is_active`) -- that
    detail now lives one tap further in, on Task Details, the "selected
    entity" screen where showing it isn't duplication.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Take out trash", is_active=False)
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    list_text, list_keyboard = _adult_tasks_list_view(telegram_id)

    assert list_text == "Все задачи"
    assert list_keyboard is not None
    assert list_keyboard.inline_keyboard[0][0].text == "❌ Take out trash"

    details_text, _ = _task_details_view(telegram_id, str(task.id))

    assert "Take out trash" in details_text
    assert "Alex" in details_text
    assert "выполняется" in details_text


def test_completed_execution_does_not_suppress_availability_in_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room")
    real.make_execution(task, child, TaskExecutionStatus.COMPLETED)

    _text, keyboard = _adult_tasks_list_view(telegram_id)

    # A terminal execution never counts against availability -- the
    # button's name stays plain (not struck through), and the Task
    # remains active.
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "Clean room · 💰 20"


def test_child_cannot_access_adult_tasks_management(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _adult_tasks_list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_tasks_view_for_unconnected_account() -> None:
    text, keyboard = _tasks_command_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Task Details / navigation
# =========================================================================================


def test_adult_can_open_task_details(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)

    text, keyboard = _task_details_view(telegram_id, str(task.id))

    assert "Clean room" in text
    assert "20 баллов" in text
    assert "Доступна" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "Изменить" in labels
    assert "Деактивировать" in labels
    assert any("Задачи" in label for label in labels)


def test_task_details_with_current_execution_hides_edit_but_not_activate_deactivate(
    real: RealData,
) -> None:
    """Issue #37: a current open execution only blocks Edit -- Activate/
    Deactivate stay available and reflect the Task's actual (independent)
    `is_active` status.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=False)
    real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text, keyboard = _task_details_view(telegram_id, str(task.id))

    assert "Alex" in text
    assert "ожидает подтверждения" in text
    assert "Недоступна" in text
    assert "Нельзя изменить название или награду, пока это выполнение открыто." in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "Изменить" not in labels
    assert "Активировать" in labels
    assert "Деактивировать" not in labels


def test_open_nonexistent_task_does_not_strand_the_user(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _task_details_view(telegram_id, str(uuid.uuid4()))

    assert text == _TASK_NOT_FOUND_TEXT
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].callback_data == LIST_CALLBACK_DATA


def test_child_cannot_open_adult_task_details_via_crafted_callback(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)

    text, keyboard = _task_details_view(telegram_id, str(task.id))

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Create Task
# =========================================================================================


def test_adult_can_start_create_task(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is True
    assert "называется" in text.lower()


def test_child_cannot_start_create_task(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is False
    assert text == _NOT_AN_ADULT_TEXT


def test_valid_creation_succeeds_end_to_end(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    flow: dict[str, object] = {"action": "create", "step": "title"}
    text, keyboard, finished = _route_flow_text(telegram_id, flow, "Clean room")
    assert finished is False
    assert flow["step"] == "reward"

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "20")
    assert finished is True
    assert "Clean room" in text
    assert "20 баллов" in text
    assert keyboard is not None

    created = real.session.query(Task).filter_by(title="Clean room", created_by=adult.id).one()
    real.task_ids.append(created.id)
    assert created.reward_points == 20
    assert created.is_active is True


def test_blank_title_is_rejected_and_stays_on_the_same_step(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    flow: dict[str, object] = {"action": "create", "step": "title"}
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "   ")

    assert finished is False
    assert flow["step"] == "title"


def test_non_numeric_reward_is_rejected_and_stays_on_the_same_step(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    flow: dict[str, object] = {"action": "create", "step": "reward", "title": "Clean room"}
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "not a number")

    assert finished is False
    assert "целое число" in text.lower()


def test_non_positive_reward_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    flow: dict[str, object] = {"action": "create", "step": "reward", "title": "Clean room"}
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "0")

    assert finished is False
    assert "больше 0" in text


def test_create_rejects_a_child_via_crafted_flow_state(real: RealData) -> None:
    """Even if a Child somehow had `adult_task_flow` state (e.g. a stale
    context), the Application layer must still refuse the creation.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _finish_create(telegram_id, "Hacked task", 20)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None
    assert real.session.query(Task).filter_by(title="Hacked task").count() == 0


# =========================================================================================
# Edit Task
# =========================================================================================


def test_adult_can_edit_task_name(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room")

    text, keyboard = _finish_edit_title(telegram_id, str(task.id), "Tidy room")

    assert "Tidy room" in text
    assert keyboard is not None
    real.session.refresh(task)
    assert task.title == "Tidy room"


def test_adult_can_edit_task_reward(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, reward_points=20)

    text, keyboard = _finish_edit_reward(telegram_id, str(task.id), 30)

    assert "30 баллов" in text
    real.session.refresh(task)
    assert task.reward_points == 30


def test_edit_menu_unavailable_while_a_current_execution_exists(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=False)
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    text, keyboard = _start_edit_menu(telegram_id, str(task.id))

    assert text == _TASK_NOT_EDITABLE_TEXT
    assert keyboard is not None


def test_start_edit_field_unavailable_while_a_current_execution_exists(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=False)
    real.make_execution(task, child, TaskExecutionStatus.ASSIGNED)

    text, keyboard, should_start = _start_edit_field(telegram_id, str(task.id), "title")

    assert should_start is False
    assert text == _TASK_NOT_EDITABLE_TEXT
    assert keyboard is not None


def test_child_cannot_edit_a_task(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult, title="Clean room")

    text, keyboard = _finish_edit_title(telegram_id, str(task.id), "Hacked")

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None
    real.session.refresh(task)
    assert task.title == "Clean room"


# =========================================================================================
# Activate / Deactivate
# =========================================================================================


def test_adult_can_deactivate_a_task(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=True)

    toast, text, keyboard = _toggle_active(telegram_id, str(task.id), activate=False)

    assert "деактивирована" in toast
    assert "Недоступна" in text
    assert keyboard is not None
    real.session.refresh(task)
    assert task.is_active is False


def test_adult_can_activate_a_task(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=False)

    toast, text, keyboard = _toggle_active(telegram_id, str(task.id), activate=True)

    assert "активирована" in toast
    assert "Доступна" in text
    real.session.refresh(task)
    assert task.is_active is True


def test_deactivate_succeeds_while_a_current_execution_exists(
    real: RealData,
) -> None:
    """Issue #37: deactivating is never blocked by an open execution, and
    never touches it -- the execution is still there, untouched, on the
    refreshed Task Details underneath the toast.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=True)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    toast, text, keyboard = _toggle_active(telegram_id, str(task.id), activate=False)

    assert "деактивирована" in toast
    assert "Недоступна" in text
    assert keyboard is not None
    real.session.refresh(task)
    assert task.is_active is False
    real.session.refresh(execution)
    assert execution.status == TaskExecutionStatus.IN_PROGRESS


def test_child_cannot_activate_or_deactivate_via_crafted_callback(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult, is_active=True)

    toast, _text, _keyboard = _toggle_active(telegram_id, str(task.id), activate=False)

    assert toast == _NOT_AN_ADULT_TEXT
    real.session.refresh(task)
    assert task.is_active is True


# =========================================================================================
# Back navigation
# =========================================================================================


def test_back_to_tasks_from_details_shows_the_list_again(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.make_task(adult, title="Clean room")

    text, keyboard = _adult_tasks_list_view(telegram_id)

    assert text == "Все задачи"
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Clean room" in label for label in labels)


def test_open_and_edit_callback_prefixes_do_not_collide() -> None:
    """A defensive assertion on the callback-routing scheme itself: `edit`
    must not accidentally prefix-match `editname`/`editreward`.
    """
    assert not "adulttask:editname:123".startswith(EDIT_CALLBACK_PREFIX)
    assert not "adulttask:editreward:123".startswith(EDIT_CALLBACK_PREFIX)
    assert not "adulttask:deactivate:123".startswith(ACTIVATE_CALLBACK_PREFIX)
    assert not "adulttask:activate:123".startswith(DEACTIVATE_CALLBACK_PREFIX)


def test_assign_and_assignto_prefixes_do_not_collide() -> None:
    assert not "adulttask:assignto:123:456".startswith(ASSIGN_CALLBACK_PREFIX)
    assert not "adulttask:assign:123".startswith(ASSIGN_TO_CALLBACK_PREFIX)


# =========================================================================================
# Issue #32: direct assignment
# =========================================================================================


def test_assign_menu_lists_eligible_children(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    free_child = real.make_user(CHILD, "Free Child")
    busy_child = real.make_user(CHILD, "Busy Child")
    real.make_execution(task, busy_child, TaskExecutionStatus.IN_PROGRESS)

    text, keyboard = _assign_menu_view(telegram_id, str(task.id))

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any(free_child.name in label for label in labels)
    assert not any(busy_child.name in label for label in labels)


def test_assign_children_keyboard_callback_data_fits_within_telegrams_64_byte_limit() -> None:
    """Regression for the `Button_data_invalid` bug: `assign_children_keyboard()`
    used to embed both the Task's UUID and each Child's UUID in their full
    36-char hyphenated form, so a Child button's callback_data exceeded
    Telegram's 64-byte `callback_data` limit and Telegram rejected the
    whole keyboard on `edit_message_text()`. Must check *encoded bytes*,
    not `len(str)` -- the limit is byte-based and the payload is UTF-8.
    """
    task_id = uuid.uuid4()
    children = [User(name="Alex", role=UserRole.CHILD, id=uuid.uuid4())]

    keyboard = assign_children_keyboard(task_id, children)

    for row in keyboard.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_assign_children_keyboard_callback_data_round_trips_to_the_correct_task_and_child() -> None:
    task_id = uuid.uuid4()
    child_id = uuid.uuid4()
    children = [User(name="Alex", role=UserRole.CHILD, id=child_id)]

    keyboard = assign_children_keyboard(task_id, children)

    button = keyboard.inline_keyboard[0][0]
    assert button.callback_data is not None
    payload = button.callback_data.removeprefix(ASSIGN_TO_CALLBACK_PREFIX)
    raw_task_token, _, raw_child_token = payload.partition(":")

    assert decode_uuid(raw_task_token) == task_id
    assert decode_uuid(raw_child_token) == child_id


def test_assign_menu_shows_a_message_when_no_children_are_eligible(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)

    text, keyboard = _assign_menu_view(telegram_id, str(task.id))

    assert "нет подходящих детей" in text


def test_child_cannot_open_the_assign_menu(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    other_adult = real.make_user(ADULT)
    task = real.make_task(other_adult)

    text, keyboard = _assign_menu_view(telegram_id, str(task.id))

    assert text == _NOT_AN_ADULT_TEXT


def test_assigning_a_task_creates_an_assigned_execution(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room")
    child = real.make_user(CHILD, "Alex")

    text, keyboard = _finish_assign(telegram_id, str(task.id), str(child.id))

    assert "Alex" in text
    assert "Clean room" in text
    session = SessionLocal()
    try:
        execution = session.query(TaskExecution).filter_by(task_id=task.id, user_id=child.id).one()
        assert execution.status == TaskExecutionStatus.ASSIGNED
        assert execution.reward_points == task.reward_points
    finally:
        session.close()


def test_assigning_a_task_does_not_change_is_active(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, is_active=True)
    child = real.make_user(CHILD, "Alex")

    _finish_assign(telegram_id, str(task.id), str(child.id))

    session = SessionLocal()
    try:
        refreshed = session.get(Task, task.id)
        assert refreshed is not None
        assert refreshed.is_active is True
    finally:
        session.close()


def test_assigning_to_a_child_with_an_open_execution_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    child = real.make_user(CHILD, "Alex")
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    text, keyboard = _finish_assign(telegram_id, str(task.id), str(child.id))

    assert text == _ALREADY_OPEN_TEXT
    session = SessionLocal()
    try:
        count = session.query(TaskExecution).filter_by(task_id=task.id, user_id=child.id).count()
        assert count == 1
    finally:
        session.close()


def test_crafted_callback_cannot_assign_a_task_to_an_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    other_adult = real.make_user(ADULT, "Other Adult")

    text, keyboard = _finish_assign(telegram_id, str(task.id), str(other_adult.id))

    assert text == _CHILD_NOT_FOUND_TEXT
    session = SessionLocal()
    try:
        count = session.query(TaskExecution).filter_by(task_id=task.id).count()
        assert count == 0
    finally:
        session.close()


def test_child_cannot_assign_a_task_even_with_a_crafted_call(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    other_adult = real.make_user(ADULT)
    task = real.make_task(other_adult)
    other_child = real.make_user(CHILD, "Other Child")

    text, keyboard = _finish_assign(telegram_id, str(task.id), str(other_child.id))

    assert text == _NOT_AN_ADULT_TEXT
    session = SessionLocal()
    try:
        count = session.query(TaskExecution).filter_by(task_id=task.id).count()
        assert count == 0
    finally:
        session.close()
