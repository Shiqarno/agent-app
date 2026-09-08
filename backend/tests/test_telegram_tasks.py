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
from app.telegram.handlers.tasks import (
    _EXECUTION_UNACTIONABLE_TEXT,
    _NOT_CONNECTED_TEXT,
    _TASK_UNAVAILABLE_TEXT,
    _mark_ready,
    _my_tasks_view,
    _start_execution,
    _take_task,
    _tasks_view,
)
from app.telegram.keyboards.tasks import (
    EXECUTION_DONE_CALLBACK_PREFIX,
    EXECUTION_START_CALLBACK_PREFIX,
    TASKS_CALLBACK_PREFIX,
)
from app.telegram.views.tasks import (
    AVAILABLE_TASKS_HEADING,
    MY_TASKS_HEADING,
    NO_TASKS_AVAILABLE_TEXT,
    NO_TASKS_IN_PROGRESS_TEXT,
)
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """The Telegram handlers under test open their own `SessionLocal()`
    (there's no FastAPI dependency-injected `db_session` in a bot process --
    see handlers/start.py), which is a genuinely separate, independently-
    committing connection from the savepoint-isolated `db_session` fixture
    used elsewhere in this suite. Setup for these tests must therefore use a
    real session too, exactly like this project's existing concurrency
    tests, with explicit cleanup since nothing here is rolled back for free.
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
    """`db_session` is only depended on to inherit the autouse test-database
    setup/isolation fixtures; it is not otherwise used here.
    """
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
# Rendering
# =========================================================================================


def test_tasks_view_renders_available_tasks(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)

    text, keyboard = _tasks_view(telegram_id)

    # Issue #36: the heading is the ENTIRE message text -- the task name
    # and reward live only on the button, never duplicated as text above it.
    assert text == AVAILABLE_TASKS_HEADING
    assert "Clean room" not in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == f"{TASKS_CALLBACK_PREFIX}{task.id}"
    assert keyboard.inline_keyboard[0][0].text == "Clean room · 💰 20"


def test_tasks_view_renders_multiple_tasks_as_separate_buttons(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task_a = real.make_task(adult, title="Wash dishes", reward_points=10)
    task_b = real.make_task(adult, title="Walk the dog", reward_points=15)

    text, keyboard = _tasks_view(telegram_id)

    assert text == AVAILABLE_TASKS_HEADING
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2
    labels = {row[0].text for row in keyboard.inline_keyboard}
    assert labels == {"Wash dishes · 💰 10", "Walk the dog · 💰 15"}
    callback_datas = {row[0].callback_data for row in keyboard.inline_keyboard}
    assert callback_datas == {
        f"{TASKS_CALLBACK_PREFIX}{task_a.id}",
        f"{TASKS_CALLBACK_PREFIX}{task_b.id}",
    }


def test_tasks_view_with_no_tasks(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _tasks_view(telegram_id)

    assert text == f"{AVAILABLE_TASKS_HEADING}\n\n{NO_TASKS_AVAILABLE_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_tasks_view_for_unconnected_account() -> None:
    text, keyboard = _tasks_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


def test_my_tasks_view_renders_in_progress_with_done_button(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    text, keyboard = _my_tasks_view(telegram_id)

    # Issue #36: an IN_PROGRESS item is fully represented by its Done
    # button -- its name never appears as separate text.
    assert text == MY_TASKS_HEADING
    assert "Clean room" not in text
    assert "Waiting for confirmation" not in text
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].callback_data == (
        f"{EXECUTION_DONE_CALLBACK_PREFIX}{execution.id}"
    )
    assert keyboard.inline_keyboard[0][0].text == "Clean room · 💰 20"


def test_my_tasks_view_awaiting_confirmation_has_no_cta(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    text, keyboard = _my_tasks_view(telegram_id)

    assert "Waiting for confirmation" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_my_tasks_view_with_no_tasks(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, _ = _my_tasks_view(telegram_id)

    assert text == f"{MY_TASKS_HEADING}\n\n{NO_TASKS_IN_PROGRESS_TEXT}"


# =========================================================================================
# Take
# =========================================================================================


def test_take_routes_to_claim_task_and_creates_in_progress_execution(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)

    toast, text, keyboard = _take_task(telegram_id, str(task.id))

    assert toast == "Clean room started."
    real.session.expire_all()
    execution = real.session.query(TaskExecution).filter_by(task_id=task.id, user_id=child.id).one()
    assert execution.status == TaskExecutionStatus.IN_PROGRESS
    # The refreshed Tasks view no longer offers the just-claimed task.
    assert text == f"{AVAILABLE_TASKS_HEADING}\n\n{NO_TASKS_AVAILABLE_TEXT}"
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_take_on_already_claimed_task_is_a_friendly_error(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    task.is_active = False
    real.session.commit()

    toast, text, keyboard = _take_task(telegram_id, str(task.id))

    assert toast == _TASK_UNAVAILABLE_TEXT
    # Handler leaves the user in a usable navigation state -- the refreshed
    # list, not a crash or a stale message.
    assert text == f"{AVAILABLE_TASKS_HEADING}\n\n{NO_TASKS_AVAILABLE_TEXT}"
    assert keyboard is not None


def test_take_with_a_bogus_task_id_does_not_crash(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    toast, _, keyboard = _take_task(telegram_id, "not-a-uuid")

    assert toast == _TASK_UNAVAILABLE_TEXT
    assert keyboard is not None


def test_take_for_unconnected_account() -> None:
    toast, _, keyboard = _take_task(_next_telegram_id(), str(uuid.uuid4()))

    assert toast == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Done
# =========================================================================================


def test_done_routes_to_mark_execution_ready(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    toast, text, keyboard = _mark_ready(telegram_id, str(execution.id))

    assert toast == "Clean room marked as done and sent for confirmation."
    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.AWAITING_CONFIRMATION
    assert "Waiting for confirmation" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_done_on_a_stale_execution_is_a_friendly_error(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.AWAITING_CONFIRMATION)

    toast, _, keyboard = _mark_ready(telegram_id, str(execution.id))

    assert toast == _EXECUTION_UNACTIONABLE_TEXT
    assert keyboard is not None


# =========================================================================================
# Issue #32: assigned executions in My Tasks, and the Start action
# =========================================================================================


def test_my_tasks_view_renders_assigned_with_start_button(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    real.make_execution(task, child, TaskExecutionStatus.ASSIGNED)

    text, keyboard = _my_tasks_view(telegram_id)

    # Issue #36: an ASSIGNED item is likewise fully represented by its
    # Start button -- no "Assigned to you" text and no "Start" verb.
    assert text == MY_TASKS_HEADING
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any(label == "Clean room · 💰 20" for label in labels)
    assert not any("Start" in label for label in labels)


def test_my_tasks_buttons_use_the_execution_reward_snapshot_not_the_current_task_reward(
    real: RealData,
) -> None:
    """Issue #35: if the Task's reward changed after an execution started,
    the Start/Done button must still show the execution's own immutable
    snapshot, not the Task's current (different) value.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult, reward_points=20)
    real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS, reward_points=20)
    task.reward_points = 99
    real.session.commit()

    _text, keyboard = _my_tasks_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("💰 20" in label for label in labels)
    assert not any("💰 99" in label for label in labels)


def test_start_routes_to_start_execution(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.ASSIGNED)

    toast, text, keyboard = _start_execution(telegram_id, str(execution.id))

    assert toast == "Clean room started."
    real.session.expire_all()
    refreshed = real.session.get(TaskExecution, execution.id)
    assert refreshed is not None
    assert refreshed.status == TaskExecutionStatus.IN_PROGRESS
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any(label == "Clean room · 💰 20" for label in labels)


def test_start_does_not_create_a_second_execution_via_telegram(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.ASSIGNED)

    _start_execution(telegram_id, str(execution.id))

    real.session.expire_all()
    count = real.session.query(TaskExecution).filter_by(task_id=task.id).count()
    assert count == 1


def test_start_on_a_stale_execution_is_a_friendly_error(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    task = real.make_task(adult)
    execution = real.make_execution(task, child, TaskExecutionStatus.IN_PROGRESS)

    toast, _, keyboard = _start_execution(telegram_id, str(execution.id))

    assert toast == _EXECUTION_UNACTIONABLE_TEXT
    assert keyboard is not None


def test_start_and_done_prefixes_do_not_collide() -> None:
    assert not "execution:start:123".startswith(EXECUTION_DONE_CALLBACK_PREFIX)
    assert not "execution:done:123".startswith(EXECUTION_START_CALLBACK_PREFIX)


def test_handlers_do_not_bypass_the_application_layer(real: RealData) -> None:
    """An Adult manually crafting a Take callback must be rejected by the
    Application layer, not merely by a hidden button (Issue #24 section
    18/8) -- proving the handler always calls through rather than trusting
    Telegram-side role assumptions.
    """
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    task = real.make_task(adult, title="Adult task")

    toast, _, _ = _take_task(telegram_id, str(task.id))
    assert toast == "This isn't available for your account."

    real.session.expire_all()
    assert real.session.query(TaskExecution).filter_by(task_id=task.id).count() == 0
