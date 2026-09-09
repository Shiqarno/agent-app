import asyncio
import uuid

from sqlalchemy.orm import Session
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import User
from app.reward_operations import InsufficientPointsError as RewardInsufficientPointsError
from app.reward_operations import NotAnAdultError as RewardNotAnAdultError
from app.reward_operations import RewardRedemptionNotActionableError, get_pending_reward_requests
from app.reward_operations import confirm_reward_redemption as confirm_reward_redemption_op
from app.reward_operations import reject_reward_redemption as reject_reward_redemption_op
from app.task_operations import (
    NotAnAdultError,
    TaskExecutionNotConfirmableError,
    confirm_execution,
    get_pending_confirmations,
    return_execution_to_work,
)
from app.telegram.keyboards.confirmations import (
    CONFIRM_CALLBACK_PREFIX,
    CONFIRM_REWARD_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    OPEN_REWARD_CALLBACK_PREFIX,
    RETURN_CALLBACK_PREFIX,
    RETURN_REWARD_CALLBACK_PREFIX,
    confirmation_detail_keyboard,
    confirmation_list_keyboard,
    reward_confirmation_detail_keyboard,
)
from app.telegram.views.confirmations import (
    ConfirmationItem,
    RewardConfirmationItem,
    TaskConfirmationItem,
    render_confirmation_detail,
    render_confirmation_list,
    render_execution_confirmed,
    render_execution_returned,
    render_reward_confirmation_detail,
    render_reward_redemption_confirmed,
    render_reward_redemption_rejected,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_AN_ADULT_TEXT = "This isn't available for your account."
_EXECUTION_UNCONFIRMABLE_TEXT = "This task is no longer waiting for confirmation."
_REWARD_REQUEST_UNACTIONABLE_TEXT = "This reward request is no longer waiting for confirmation."
_REWARD_REQUEST_INSUFFICIENT_BALANCE_TEXT = (
    "This can't be confirmed right now -- the child's balance is too low. "
    "The request is still pending; try again once their balance recovers, or Return it."
)


def _combined_confirmation_items(db: Session, user: User) -> list[ConfirmationItem]:
    """Task confirmations and Reward requests, merged into the one queue
    /confirmations (and Adult Home) presents (Issue #39) -- oldest first,
    matching each source's own existing ordering. Raises NotAnAdultError /
    reward_operations.NotAnAdultError (the two are distinct exception
    classes, one per Application-layer module) if `user` isn't an Adult;
    callers already check that before reaching here in every path that
    calls this.
    """
    task_items = get_pending_confirmations(db, user)
    reward_items = get_pending_reward_requests(db, user)
    task_wrapped: list[ConfirmationItem] = [
        TaskConfirmationItem(execution, task, child) for execution, task, child in task_items
    ]
    reward_wrapped: list[ConfirmationItem] = [
        RewardConfirmationItem(redemption, reward, child)
        for redemption, reward, child in reward_items
    ]
    return sorted(task_wrapped + reward_wrapped, key=lambda item: item.created_at)


def _list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = _combined_confirmation_items(db, user)
        except (NotAnAdultError, RewardNotAnAdultError):
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
            return _EXECUTION_UNCONFIRMABLE_TEXT, confirmation_list_keyboard(
                _combined_confirmation_items(db, user)
            )

        match = next((item for item in items if item[0].id == execution_id), None)
        if match is None:
            return _EXECUTION_UNCONFIRMABLE_TEXT, confirmation_list_keyboard(
                _combined_confirmation_items(db, user)
            )

        execution, task, child = match
        return render_confirmation_detail(execution, task, child), confirmation_detail_keyboard(
            execution
        )
    finally:
        db.close()


def _reward_detail_view(
    telegram_user_id: int, raw_redemption_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    """The Reward request analogue of _detail_view above (Issue #39)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_pending_reward_requests(db, user)
        except RewardNotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None

        try:
            redemption_id = uuid.UUID(raw_redemption_id)
        except ValueError:
            return _REWARD_REQUEST_UNACTIONABLE_TEXT, confirmation_list_keyboard(
                _combined_confirmation_items(db, user)
            )

        match = next((item for item in items if item[0].id == redemption_id), None)
        if match is None:
            return _REWARD_REQUEST_UNACTIONABLE_TEXT, confirmation_list_keyboard(
                _combined_confirmation_items(db, user)
            )

        redemption, reward, child = match
        return (
            render_reward_confirmation_detail(redemption, reward, child),
            reward_confirmation_detail_keyboard(redemption),
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
            items = _combined_confirmation_items(db, user)
        except (NotAnAdultError, RewardNotAnAdultError):
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
            items = _combined_confirmation_items(db, user)
        except (NotAnAdultError, RewardNotAnAdultError):
            return toast, _NOT_AN_ADULT_TEXT, None
        return toast, render_confirmation_list(items), confirmation_list_keyboard(items)
    finally:
        db.close()


def _confirm_reward(
    telegram_user_id: int, raw_redemption_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """The Reward request analogue of _confirm above (Issue #39). A
    request that can no longer be safely confirmed (Issue #40: the
    Child's balance dropped below the frozen cost, e.g. via a manual
    adjustment) is left pending rather than acted on -- see
    confirm_reward_redemption's own docstring.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            redemption_id = uuid.UUID(raw_redemption_id)
            redemption, reward, child = confirm_reward_redemption_op(db, user, redemption_id)
            toast = render_reward_redemption_confirmed(redemption, reward, child)
        except (ValueError, RewardRedemptionNotActionableError):
            toast = _REWARD_REQUEST_UNACTIONABLE_TEXT
        except RewardInsufficientPointsError:
            toast = _REWARD_REQUEST_INSUFFICIENT_BALANCE_TEXT
        except RewardNotAnAdultError:
            toast = _NOT_AN_ADULT_TEXT

        try:
            items = _combined_confirmation_items(db, user)
        except (NotAnAdultError, RewardNotAnAdultError):
            return toast, _NOT_AN_ADULT_TEXT, None
        return toast, render_confirmation_list(items), confirmation_list_keyboard(items)
    finally:
        db.close()


def _reject_reward(
    telegram_user_id: int, raw_redemption_id: str
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """The Reward request analogue of _return_to_work above (Issue #39):
    `Return` on a Reward request means reject it, releasing its freeze
    without ever creating a REWARD_REDEEMED transaction.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            redemption_id = uuid.UUID(raw_redemption_id)
            _, reward, child = reject_reward_redemption_op(db, user, redemption_id)
            toast = render_reward_redemption_rejected(reward, child)
        except (ValueError, RewardRedemptionNotActionableError):
            toast = _REWARD_REQUEST_UNACTIONABLE_TEXT
        except RewardNotAnAdultError:
            toast = _NOT_AN_ADULT_TEXT

        try:
            items = _combined_confirmation_items(db, user)
        except (NotAnAdultError, RewardNotAnAdultError):
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


async def handle_open_reward_confirmation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_redemption_id = query.data.removeprefix(OPEN_REWARD_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _reward_detail_view, update.effective_user.id, raw_redemption_id
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


async def handle_confirm_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_redemption_id = query.data.removeprefix(CONFIRM_REWARD_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _confirm_reward, update.effective_user.id, raw_redemption_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_return_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_redemption_id = query.data.removeprefix(RETURN_REWARD_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _reject_reward, update.effective_user.id, raw_redemption_id
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
