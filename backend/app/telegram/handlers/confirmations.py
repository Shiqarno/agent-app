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
    OPEN_CALLBACK_PREFIX,
    RETURN_CALLBACK_PREFIX,
    confirmation_detail_keyboard,
    confirmation_list_keyboard,
)
from app.telegram.views.confirmations import (
    render_confirmation_detail,
    render_confirmation_list,
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


def _list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_pending_confirmations(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        return render_confirmation_list(items), confirmation_list_keyboard(items)
    finally:
        db.close()


def _detail_view(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Issue #36 step 2: resolves the *specific* execution the Adult tapped
    in step 1, by filtering the same `get_pending_confirmations` result the
    list itself is built from -- no new Application-layer lookup, and no
    possibility of showing a different execution than the one identified by
    the callback (never the task name).
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_pending_confirmations(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None

        try:
            execution_id = uuid.UUID(raw_execution_id)
        except ValueError:
            return _EXECUTION_UNCONFIRMABLE_TEXT, confirmation_list_keyboard(items)

        match = next((item for item in items if item[0].id == execution_id), None)
        if match is None:
            return _EXECUTION_UNCONFIRMABLE_TEXT, confirmation_list_keyboard(items)

        execution, task, child = match
        return render_confirmation_detail(execution, task, child), confirmation_detail_keyboard(
            execution
        )
    finally:
        db.close()


def _confirm(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed list message text, refreshed
    keyboard) -- after acting, the Adult lands back on step 1 (the list),
    since the just-acted-on execution is no longer awaiting confirmation
    and there is nothing left to show on its detail screen. A stale/invalid
    Confirm is handled the same way as any other rejection (Issue #25
    section 24): the Application operation is called anyway, its rejection
    becomes a friendly toast, and the list underneath is refreshed to
    current state rather than left stale.
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
        return toast, render_confirmation_list(items), confirmation_list_keyboard(items)
    finally:
        db.close()


def _return_to_work(
    telegram_user_id: int, raw_execution_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, refreshed list message text, refreshed
    keyboard) -- same post-action navigation as _confirm above.
    """
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
        return toast, render_confirmation_list(items), confirmation_list_keyboard(items)
    finally:
        db.close()


async def handle_confirmations_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_list_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_view_all_confirmations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, keyboard = await asyncio.to_thread(_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_open_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_execution_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _detail_view, update.effective_user.id, raw_execution_id
    )
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
