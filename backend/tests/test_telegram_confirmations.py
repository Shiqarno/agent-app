import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import (
    PointTransaction,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.handlers.confirmations import (
    _EXECUTION_UNCONFIRMABLE_TEXT,
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _confirm,
    _detail_view,
    _list_view,
    _return_to_work,
)
from app.telegram.keyboards.confirmations import (
    CONFIRM_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    RETURN_CALLBACK_PREFIX,
    VIEW_ALL_CALLBACK_DATA,
)
from app.telegram.views.confirmations import CONFIRMATIONS_HEADING, NO_CONFIRMATIONS_TEXT
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """Same rationale as test_telegram_tasks.py's RealData: the handlers
    under test open their own `SessionLocal()`, a genuinely separate,
    independently-committing connection from the savepoint-isolated
    `db_session` fixture, so setup here must use a real session too.
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
        self, creator: User, *, title: str = "Clean room", reward_points: int = 20
    ) -> Task:
        task = Task(title=title, reward_points=reward_points, created_by=creator.id)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task_ids.append(task.id)
        return task

    def make_execution(
        self,
        task: Task,
        user: User,
        status: TaskExecutionStatus,
        *,
        reward_points: int | None = None,
    ) -> TaskExecution:
        execution = TaskExecution(
            task_id=task.id,
            user_id=user.id,
            status=status,
            reward_points=reward_points if reward_points is not None else task.reward_points,
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
# Step 1: confirmation list
# =========================================================================================


def test_adult_can_render_the_confirmation_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Vova")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text, keyboard = _list_view(telegram_id)

    # Issue #36: the heading is the ENTIRE message text -- the Task name is
    # never duplicated as text above the button; it lives only there.
    assert text == CONFIRMATIONS_HEADING
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].text == "Clean room · Vova"
    assert keyboard.inline_keyboard[0][0].callback_data == f"{OPEN_CALLBACK_PREFIX}{execution.id}"


def test_multiple_confirmations_produce_one_button_each_with_distinct_execution_ids(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    child_a = real.make_user(CHILD, "Alex")
    child_b = real.make_user(CHILD, "Blair")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task_a = real.make_task(adult, title="Wash dishes", reward_points=10)
    task_b = real.make_task(adult, title="Clean room", reward_points=20)
    execution_a = real.make_execution(task_a, child_a, TaskExecutionStatus.AWAITING_CONFIRMATION)
    execution_b = real.make_execution(task_b, child_b, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text, keyboard = _list_view(telegram_id)

    assert text == CONFIRMATIONS_HEADING
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2
    labels = {row[0].text for row in keyboard.inline_keyboard}
    assert labels == {"Wash dishes · Alex", "Clean room · Blair"}
    callback_datas = {row[0].callback_data for row in keyboard.inline_keyboard}
    assert callback_datas == {
        f"{OPEN_CALLBACK_PREFIX}{execution_a.id}",
        f"{OPEN_CALLBACK_PREFIX}{execution_b.id}",
    }


def test_same_task_for_two_children_produces_two_distinguishable_buttons(
    real: RealData,
) -> None:
    """Issue #36: a title-only button would be ambiguous when two Children
    both have an execution of the same Task -- the Child name on each
    button is what disambiguates them.
    """
    adult = real.make_user(ADULT)
    child_a = real.make_user(CHILD, "Alice")
    child_b = real.make_user(CHILD, "Bob")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)
    execution_a = real.make_execution(task, child_a, TaskExecutionStatus.AWAITING_CONFIRMATION)
    execution_b = real.make_execution(task, child_b, TaskExecutionStatus.AWAITING_CONFIRMATION)

    _text, keyboard = _list_view(telegram_id)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2
    labels = {row[0].text for row in keyboard.inline_keyboard}
    assert labels == {"Clean room · Alice", "Clean room · Bob"}
    by_label = {row[0].text: row[0].callback_data for row in keyboard.inline_keyboard}
    assert by_label["Clean room · Alice"] == f"{OPEN_CALLBACK_PREFIX}{execution_a.id}"
    assert by_label["Clean room · Bob"] == f"{OPEN_CALLBACK_PREFIX}{execution_b.id}"


def test_child_cannot_use_confirmation_actions(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_empty_list_renders_correctly(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _list_view(telegram_id)

    assert text == f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_list_view_for_unconnected_account() -> None:
    text, keyboard = _list_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Step 2: selected confirmation
# =========================================================================================


def test_opening_a_confirmation_shows_its_task_name_and_actions(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Vova")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text, keyboard = _detail_view(telegram_id, str(execution.id))

    assert "Clean room" in text
    assert "Vova" in text
    assert "20" in text
    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    confirm = next(b for b in buttons if b.text == "Confirm")
    ret = next(b for b in buttons if b.text == "Return")
    assert confirm.callback_data == f"{CONFIRM_CALLBACK_PREFIX}{execution.id}"
    assert ret.callback_data == f"{RETURN_CALLBACK_PREFIX}{execution.id}"


def test_detail_view_has_a_way_back_to_the_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    _text, keyboard = _detail_view(telegram_id, str(execution.id))

    assert keyboard is not None
    callback_datas = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert VIEW_ALL_CALLBACK_DATA in callback_datas


def test_selecting_one_task_shows_only_that_executions_controls(real: RealData) -> None:
    """Issue #36 execution isolation: opening Task A must never surface
    Task B's controls, and vice versa.
    """
    adult = real.make_user(ADULT)
    child_a = real.make_user(CHILD, "Alex")
    child_b = real.make_user(CHILD, "Blair")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task_a = real.make_task(adult, title="Wash dishes", reward_points=10)
    task_b = real.make_task(adult, title="Clean room", reward_points=20)
    execution_a = real.make_execution(task_a, child_a, TaskExecutionStatus.AWAITING_CONFIRMATION)
    execution_b = real.make_execution(task_b, child_b, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text_a, keyboard_a = _detail_view(telegram_id, str(execution_a.id))
    text_b, keyboard_b = _detail_view(telegram_id, str(execution_b.id))

    assert "Wash dishes" in text_a
    assert "Clean room" not in text_a
    assert keyboard_a is not None
    callbacks_a = [button.callback_data for row in keyboard_a.inline_keyboard for button in row]
    assert f"{CONFIRM_CALLBACK_PREFIX}{execution_a.id}" in callbacks_a
    assert f"{CONFIRM_CALLBACK_PREFIX}{execution_b.id}" not in callbacks_a

    assert "Clean room" in text_b
    assert "Wash dishes" not in text_b
    assert keyboard_b is not None
    callbacks_b = [button.callback_data for row in keyboard_b.inline_keyboard for button in row]
    assert f"{CONFIRM_CALLBACK_PREFIX}{execution_b.id}" in callbacks_b
    assert f"{CONFIRM_CALLBACK_PREFIX}{execution_a.id}" not in callbacks_b


def test_opening_a_stale_execution_falls_back_to_the_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    text, keyboard = _detail_view(telegram_id, str(execution.id))

    assert text == _EXECUTION_UNCONFIRMABLE_TEXT
    assert keyboard is not None


def test_opening_a_bogus_execution_id_does_not_crash(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _detail_view(telegram_id, "not-a-uuid")

    assert text == _EXECUTION_UNCONFIRMABLE_TEXT
    assert keyboard is not None


def test_detail_view_for_unconnected_account() -> None:
    text, keyboard = _detail_view(_next_telegram_id(), str(uuid.uuid4()))

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


def test_child_cannot_open_a_confirmation_detail(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _detail_view(telegram_id, str(uuid.uuid4()))

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Post-action navigation and isolation
# =========================================================================================


def test_confirming_one_execution_does_not_affect_another(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child_a = real.make_user(CHILD, "Alex")
    child_b = real.make_user(CHILD, "Blair")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task_a = real.make_task(adult, title="Wash dishes", reward_points=10)
    task_b = real.make_task(adult, title="Clean room", reward_points=20)
    execution_a = real.make_execution(task_a, child_a, TaskExecutionStatus.AWAITING_CONFIRMATION)
    execution_b = real.make_execution(task_b, child_b, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, text, keyboard = _confirm(telegram_id, str(execution_a.id))

    assert "Wash dishes" in toast
    real.session.expire_all()
    refreshed_a = real.session.get(TaskExecution, execution_a.id)
    refreshed_b = real.session.get(TaskExecution, execution_b.id)
    assert refreshed_a is not None
    assert refreshed_a.status == TaskExecutionStatus.COMPLETED
    assert refreshed_b is not None
    assert refreshed_b.status == TaskExecutionStatus.AWAITING_CONFIRMATION
    # Back on the (refreshed) list -- only execution B remains.
    assert text == CONFIRMATIONS_HEADING
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == f"{OPEN_CALLBACK_PREFIX}{execution_b.id}"


def test_returning_one_execution_does_not_affect_another(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child_a = real.make_user(CHILD, "Alex")
    child_b = real.make_user(CHILD, "Blair")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task_a = real.make_task(adult, title="Wash dishes", reward_points=10)
    task_b = real.make_task(adult, title="Clean room", reward_points=20)
    execution_a = real.make_execution(task_a, child_a, TaskExecutionStatus.AWAITING_CONFIRMATION)
    execution_b = real.make_execution(task_b, child_b, TaskExecutionStatus.AWAITING_CONFIRMATION)

    _return_to_work(telegram_id, str(execution_a.id))

    real.session.expire_all()
    refreshed_a = real.session.get(TaskExecution, execution_a.id)
    refreshed_b = real.session.get(TaskExecution, execution_b.id)
    assert refreshed_a is not None
    assert refreshed_a.status == TaskExecutionStatus.IN_PROGRESS
    assert refreshed_b is not None
    assert refreshed_b.status == TaskExecutionStatus.AWAITING_CONFIRMATION


# =========================================================================================
# Confirm
# =========================================================================================


def test_confirm_routes_to_confirm_execution_and_removes_it_from_the_queue(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Vova")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room", reward_points=20)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, text, keyboard = _confirm(telegram_id, str(execution.id))

    assert toast == "Clean room confirmed -- Vova earned 💰 20."
    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.COMPLETED
    transaction = (
        real.session.query(PointTransaction).filter_by(task_execution_id=execution.id).one()
    )
    assert transaction.amount == 20
    assert transaction.user_id == child.id
    # Back on the (refreshed, now empty) list.
    assert text == f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_stale_confirm_is_a_friendly_error(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    toast, text, keyboard = _confirm(telegram_id, str(execution.id))

    assert toast == _EXECUTION_UNCONFIRMABLE_TEXT
    assert keyboard is not None


def test_confirm_for_unconnected_account() -> None:
    toast, _, keyboard = _confirm(_next_telegram_id(), str(uuid.uuid4()))

    assert toast == _NOT_CONNECTED_TEXT
    assert keyboard is None


def test_child_cannot_confirm_via_a_crafted_callback(real: RealData) -> None:
    """Issue #25 section 25: the authoritative check is the Application
    layer, not hidden Telegram navigation.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, _, _ = _confirm(telegram_id, str(execution.id))

    assert toast == _NOT_AN_ADULT_TEXT
    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.AWAITING_CONFIRMATION


# =========================================================================================
# Return to work
# =========================================================================================


def test_return_routes_to_return_execution_to_work_and_removes_it_from_the_queue(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Vova")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Clean room")
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, text, keyboard = _return_to_work(telegram_id, str(execution.id))

    assert toast == "Clean room returned to Vova."
    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.IN_PROGRESS
    assert (
        real.session.query(PointTransaction).filter_by(task_execution_id=execution.id).count() == 0
    )
    assert text == f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_stale_return_is_a_friendly_error(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.COMPLETED)

    toast, _, keyboard = _return_to_work(telegram_id, str(execution.id))

    assert toast == _EXECUTION_UNCONFIRMABLE_TEXT
    assert keyboard is not None
