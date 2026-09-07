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
    _take_task,
    _tasks_view,
)
from app.telegram.keyboards.tasks import EXECUTION_DONE_CALLBACK_PREFIX, TASKS_CALLBACK_PREFIX
from app.telegram.views.tasks import NO_TASKS_AVAILABLE_TEXT, NO_TASKS_IN_PROGRESS_TEXT
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

    assert "Clean room" in text
    assert "20" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == f"{TASKS_CALLBACK_PREFIX}{task.id}"


def test_tasks_view_with_no_tasks(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _tasks_view(telegram_id)

    assert text == NO_TASKS_AVAILABLE_TEXT
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

    assert "Clean room" in text
    assert "Waiting for confirmation" not in text
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].callback_data == (
        f"{EXECUTION_DONE_CALLBACK_PREFIX}{execution.id}"
    )


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

    assert text == NO_TASKS_IN_PROGRESS_TEXT


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
    assert text == NO_TASKS_AVAILABLE_TEXT
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
    assert text == NO_TASKS_AVAILABLE_TEXT
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
