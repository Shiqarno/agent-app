import asyncio
import uuid

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.task_operations import (
    NotAnAdultError,
    TaskExecutionNotConfirmableError,
    confirm_execution,
    get_pending_confirmations,
    return_execution_to_work,
)
from app.telegram.keyboards.confirmations import (
    CONFIRM_CALLBACK_PREFIX,
    RETURN_CALLBACK_PREFIX,
    confirmation_queue_keyboard,
)
from app.telegram.views.confirmations import (
    render_confirmation_queue,
    render_execution_confirmed,
    render_execution_returned,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_AN_ADULT_TEXT = "This isn't available for your account."
_EXECUTION_UNCONFIRMABLE_TEXT = "This task is no longer waiting for confirmation."


def _queue_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_pending_confirmations(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        return render_confirmation_queue(items), confirmation_queue_keyboard(items)
    finally:
        db.close()


def _confirm(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed queue message text, refreshed keyboard).
    A stale/invalid Confirm is handled the same way as any other rejection
    (Issue #25 section 24): the Application operation is called anyway, its
    rejection becomes a friendly toast, and the queue underneath is
    refreshed to current state rather than left stale.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            execution_id = uuid.UUID(raw_execution_id)
            execution, task, child = confirm_execution(db, user, execution_id)
            toast = render_execution_confirmed(task, child, execution)
        except (ValueError, TaskExecutionNotConfirmableError):
            toast = _EXECUTION_UNCONFIRMABLE_TEXT
        except NotAnAdultError:
            toast = _NOT_AN_ADULT_TEXT

        try:
            items = get_pending_confirmations(db, user)
        except NotAnAdultError:
            return toast, _NOT_AN_ADULT_TEXT, None
        return toast, render_confirmation_queue(items), confirmation_queue_keyboard(items)
    finally:
        db.close()


def _return_to_work(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed queue message text, refreshed keyboard)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            execution_id = uuid.UUID(raw_execution_id)
            _, task, child = return_execution_to_work(db, user, execution_id)
            toast = render_execution_returned(task, child)
        except (ValueError, TaskExecutionNotConfirmableError):
            toast = _EXECUTION_UNCONFIRMABLE_TEXT
        except NotAnAdultError:
            toast = _NOT_AN_ADULT_TEXT

        try:
            items = get_pending_confirmations(db, user)
        except NotAnAdultError:
            return toast, _NOT_AN_ADULT_TEXT, None
        return toast, render_confirmation_queue(items), confirmation_queue_keyboard(items)
    finally:
        db.close()


async def handle_confirmations_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_queue_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_view_all_confirmations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, keyboard = await asyncio.to_thread(_queue_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_confirm_execution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_execution_id = query.data.removeprefix(CONFIRM_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _confirm, update.effective_user.id, raw_execution_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_return_execution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_execution_id = query.data.removeprefix(RETURN_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _return_to_work, update.effective_user.id, raw_execution_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
