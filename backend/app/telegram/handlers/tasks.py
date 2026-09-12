import asyncio
import uuid

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.task_operations import (
    NotAChildError,
    TaskExecutionNotActionableError,
    TaskNotClaimableError,
    claim_task,
    get_available_tasks,
    get_my_tasks,
    mark_execution_ready,
    start_execution,
)
from app.telegram.keyboards.tasks import (
    EXECUTION_DONE_CALLBACK_PREFIX,
    EXECUTION_START_CALLBACK_PREFIX,
    TASKS_CALLBACK_PREFIX,
    available_tasks_keyboard,
    my_tasks_keyboard,
)
from app.telegram.views.tasks import (
    render_available_tasks,
    render_execution_marked_ready,
    render_my_tasks,
    render_task_taken,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_A_CHILD_TEXT = "Это недоступно для вашего аккаунта."
_TASK_UNAVAILABLE_TEXT = "Эта задача больше не доступна."
_EXECUTION_UNACTIONABLE_TEXT = "Это действие для задачи больше не доступно."


def _tasks_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            tasks = get_available_tasks(db, user)
        except NotAChildError:
            return _NOT_A_CHILD_TEXT, None
        return render_available_tasks(tasks), available_tasks_keyboard(tasks)
    finally:
        db.close()


def _my_tasks_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_my_tasks(db, user)
        except NotAChildError:
            return _NOT_A_CHILD_TEXT, None
        return render_my_tasks(items), my_tasks_keyboard(items)
    finally:
        db.close()


def _take_task(
    telegram_user_id: int, raw_task_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed Tasks message text, refreshed keyboard).
    A stale/invalid Take is handled the same way as any other rejection
    (Issue #24 section 16): the Application operation is called anyway, its
    rejection becomes a friendly toast, and the view underneath is
    refreshed to current state rather than left stale.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            task_id = uuid.UUID(raw_task_id)
            execution, task = claim_task(db, user, task_id)
            toast = render_task_taken(task)
        except (ValueError, TaskNotClaimableError):
            toast = _TASK_UNAVAILABLE_TEXT
        except NotAChildError:
            toast = _NOT_A_CHILD_TEXT

        try:
            tasks = get_available_tasks(db, user)
        except NotAChildError:
            return toast, _NOT_A_CHILD_TEXT, None
        return toast, render_available_tasks(tasks), available_tasks_keyboard(tasks)
    finally:
        db.close()


def _mark_ready(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed My Tasks message text, refreshed keyboard)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            execution_id = uuid.UUID(raw_execution_id)
            execution, task = mark_execution_ready(db, user, execution_id)
            toast = render_execution_marked_ready(task)
        except (ValueError, TaskExecutionNotActionableError):
            toast = _EXECUTION_UNACTIONABLE_TEXT
        except NotAChildError:
            toast = _NOT_A_CHILD_TEXT

        try:
            items = get_my_tasks(db, user)
        except NotAChildError:
            return toast, _NOT_A_CHILD_TEXT, None
        return toast, render_my_tasks(items), my_tasks_keyboard(items)
    finally:
        db.close()


def _start_execution(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed My Tasks message text, refreshed
    keyboard) -- the Child's Start action on a directly-assigned execution
    (Issue #32), same shape as _mark_ready below.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            execution_id = uuid.UUID(raw_execution_id)
            execution, task = start_execution(db, user, execution_id)
            toast = render_task_taken(task)
        except (ValueError, TaskExecutionNotActionableError):
            toast = _EXECUTION_UNACTIONABLE_TEXT
        except NotAChildError:
            toast = _NOT_A_CHILD_TEXT

        try:
            items = get_my_tasks(db, user)
        except NotAChildError:
            return toast, _NOT_A_CHILD_TEXT, None
        return toast, render_my_tasks(items), my_tasks_keyboard(items)
    finally:
        db.close()


async def handle_my_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_my_tasks_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_take_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(TASKS_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _take_task, update.effective_user.id, raw_task_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_mark_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_execution_id = query.data.removeprefix(EXECUTION_DONE_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _mark_ready, update.effective_user.id, raw_execution_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_start_execution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_execution_id = query.data.removeprefix(EXECUTION_START_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _start_execution, update.effective_user.id, raw_execution_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
