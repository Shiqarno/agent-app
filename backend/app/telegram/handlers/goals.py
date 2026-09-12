import asyncio
import uuid
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.goal_operations import (
    ContributionExceedsRemainingAmountError,
    GoalNotActiveError,
    GoalNotFoundError,
    InsufficientPointsError,
    InvalidContributionAmountError,
    NotAChildError,
    contribute_to_goal,
    get_active_goals,
    get_goal_details,
)
from app.models import GoalStatus, UserRole, utcnow
from app.reward_operations import get_available_balance
from app.telegram.keyboards.goals import (
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    TRANSFER_CALLBACK_PREFIX,
    back_to_goal_keyboard,
    back_to_goals_keyboard,
    decode_older_payload,
    goal_details_keyboard,
    goals_list_keyboard,
    transfer_confirmation_keyboard,
)
from app.telegram.views.goals import (
    render_goal_details,
    render_goals_list,
    render_transfer_amount_prompt,
    render_transfer_confirmation,
    render_transfer_success,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_A_CHILD_TEXT = "Это недоступно для вашего аккаунта."
_GOAL_NOT_FOUND_TEXT = "Цель не найдена."
_GOAL_ALREADY_COMPLETED_TEXT = "Эта цель уже достигнута."
_EXCEEDS_REMAINING_TEXT = "Нельзя перевести больше, чем осталось до цели."
_INSUFFICIENT_POINTS_TEXT = "Недостаточно баллов."
_INVALID_AMOUNT_TEXT = "Укажи положительное целое число баллов."

# Per-chat, in-memory only (pattern established by Issue #31's Adjust
# Points flow): tracks the Goal (and, once entered, the amount) for this
# Child's in-progress transfer. Never persisted -- if the bot restarts
# mid-flow, the Child just taps "Перевести баллы" again; no business state
# depends on this, and the actual transfer is never applied until the
# Child explicitly confirms it via contribute_to_goal.
_FLOW_KEY = "goal_transfer_flow"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _goals_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goals = get_active_goals(db, user)
        except NotAChildError:
            return _NOT_A_CHILD_TEXT, None
        return render_goals_list(goals), goals_list_keyboard(goals)
    finally:
        db.close()


def _goal_details_view(
    telegram_user_id: int, raw_goal_id: str, cursor: uuid.UUID | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        try:
            view = get_goal_details(db, goal_id, cursor)
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        return render_goal_details(view, utcnow()), goal_details_keyboard(view)
    finally:
        db.close()


def _start_transfer(
    telegram_user_id: int, raw_goal_id: str
) -> tuple[str, bool, InlineKeyboardMarkup | None]:
    """Returns (text, should_start_flow, keyboard-on-failure)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False, None
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, False, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, False, back_to_goals_keyboard()
        try:
            view = get_goal_details(db, goal_id)
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, False, back_to_goals_keyboard()
        if view.goal.status != GoalStatus.ACTIVE:
            return _GOAL_ALREADY_COMPLETED_TEXT, False, back_to_goal_keyboard(goal_id)

        available_balance = get_available_balance(db, user.id)
        remaining = view.goal.cost_points - view.goal.accumulated_points
        return render_transfer_amount_prompt(available_balance, remaining), True, None
    finally:
        db.close()


def _parse_amount(text: str) -> tuple[int | None, str | None]:
    try:
        value = int(text.strip())
    except ValueError:
        return None, _INVALID_AMOUNT_TEXT
    if value <= 0:
        return None, _INVALID_AMOUNT_TEXT
    return value, None


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances the one-step Goal Transfer amount flow (Issue: Goals) by
    one text message -- not a generic conversation state machine, just
    "the next message is the transfer amount". Returns (reply text,
    keyboard, whether the flow is now finished). Deliberately does not
    finish the flow on a valid amount: the actual transfer only happens
    when the Child taps the confirmation's `Перевести` button (see
    _finish_transfer below), which reads `flow["goal_id"]`/
    `flow["amount"]` set here -- retyping a different amount before
    confirming simply re-evaluates and re-shows the confirmation for the
    new amount.
    """
    text = text.strip()
    raw_goal_id = flow.get("goal_id")
    if raw_goal_id is None:
        # Unknown/stale flow -- shouldn't be reachable, but never leave
        # the Child stuck silently ignoring their input.
        return "", None, True

    amount, error = _parse_amount(text)
    if error is not None or amount is None:
        return error or _INVALID_AMOUNT_TEXT, None, False

    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None, True
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard(), True
        try:
            view = get_goal_details(db, goal_id)
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard(), True
        if view.goal.status != GoalStatus.ACTIVE:
            return _GOAL_ALREADY_COMPLETED_TEXT, back_to_goal_keyboard(goal_id), True

        available_balance = get_available_balance(db, user.id)
        remaining = view.goal.cost_points - view.goal.accumulated_points
        if amount > remaining:
            return _EXCEEDS_REMAINING_TEXT, None, False
        if amount > available_balance:
            return _INSUFFICIENT_POINTS_TEXT, None, False

        flow["amount"] = amount
        balance_after = available_balance - amount
        return (
            render_transfer_confirmation(view.goal, amount, balance_after),
            transfer_confirmation_keyboard(goal_id),
            False,
        )
    finally:
        db.close()


def _finish_transfer(
    telegram_user_id: int, flow: dict[str, Any]
) -> tuple[str, InlineKeyboardMarkup | None]:
    raw_goal_id = flow.get("goal_id")
    amount = flow.get("amount")
    if raw_goal_id is None or amount is None:
        return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()

    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()

        try:
            _contribution, goal, _new_balance = contribute_to_goal(db, user, goal_id, amount)
        except NotAChildError:
            return _NOT_A_CHILD_TEXT, None
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        except GoalNotActiveError:
            return _GOAL_ALREADY_COMPLETED_TEXT, back_to_goal_keyboard(goal_id)
        except ContributionExceedsRemainingAmountError:
            return _EXCEEDS_REMAINING_TEXT, back_to_goal_keyboard(goal_id)
        except InsufficientPointsError:
            return _INSUFFICIENT_POINTS_TEXT, back_to_goal_keyboard(goal_id)
        except InvalidContributionAmountError:
            return _INVALID_AMOUNT_TEXT, back_to_goals_keyboard()

        view = get_goal_details(db, goal.id)
        return render_transfer_success(goal, amount), goal_details_keyboard(view)
    finally:
        db.close()


async def handle_goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_goals_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_list_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_goals_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_open_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    raw_goal_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _goal_details_view, update.effective_user.id, raw_goal_id, None
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_older_goal_contributions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw = query.data.removeprefix(OLDER_CALLBACK_PREFIX)
    # Both ids arrive base64-packed (see keyboards.goals.goal_details_keyboard)
    # so the combined payload fits Telegram's 64-byte callback_data limit;
    # decoding here is defense-in-depth only -- get_goal_details re-verifies
    # the Goal exists regardless of what the callback claims.
    goal_id, cursor = decode_older_payload(raw)
    raw_goal_id = str(goal_id) if goal_id is not None else ""
    text, keyboard = await asyncio.to_thread(
        _goal_details_view, update.effective_user.id, raw_goal_id, cursor
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_start_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_goal_id = query.data.removeprefix(TRANSFER_CALLBACK_PREFIX)
    text, should_start, keyboard = await asyncio.to_thread(
        _start_transfer, update.effective_user.id, raw_goal_id
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"goal_id": raw_goal_id}
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_confirm_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    flow = _user_data(context).get(_FLOW_KEY)
    await query.answer()
    if not flow:
        return
    text, keyboard = await asyncio.to_thread(_finish_transfer, update.effective_user.id, flow)
    _user_data(context).pop(_FLOW_KEY, None)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_goal_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Goal Transfer free-text interaction. A text message with no
    active flow is silently ignored.
    """
    if update.effective_user is None or update.message is None or update.message.text is None:
        return
    data = _user_data(context)
    flow = data.get(_FLOW_KEY)
    if not flow:
        return

    text, keyboard, finished = await asyncio.to_thread(
        _route_flow_text, update.effective_user.id, flow, update.message.text
    )
    if finished:
        data.pop(_FLOW_KEY, None)
    if text:
        await update.message.reply_text(text, reply_markup=keyboard)
