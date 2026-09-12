import asyncio
import uuid

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import UserRole
from app.reward_operations import (
    InsufficientPointsError,
    RewardNotFoundError,
    get_rewards,
    request_reward_redemption,
)
from app.telegram import notifications
from app.telegram.keyboards.rewards import REQUEST_CALLBACK_PREFIX, rewards_keyboard
from app.telegram.views.rewards import render_reward_requested, render_rewards
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_A_CHILD_TEXT = "Это недоступно для вашего аккаунта."
_REWARD_UNAVAILABLE_TEXT = "Эта награда больше не доступна."
_INSUFFICIENT_POINTS_TEXT = "Недостаточно баллов."


def _rewards_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        # Rewards requesting is a Child workflow in Telegram (Issue #26
        # Authorization) -- a presentation-level choice, not a new
        # Application-layer role rule: app.reward_operations mirrors the
        # existing Web endpoints, which have no role restriction.
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, None
        rewards, available_balance = get_rewards(db, user)
        return (
            render_rewards(rewards, available_balance),
            rewards_keyboard(rewards, available_balance),
        )
    finally:
        db.close()


def _request(
    telegram_user_id: int, raw_reward_id: str
) -> tuple[str, bool, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, whether it was a success, refreshed Rewards
    message text, refreshed keyboard). A stale/invalid request is handled
    the same way as any other rejection (Issue #26 "Stale Telegram
    interaction"): the Application operation is called anyway, its
    rejection becomes a friendly toast, and the view underneath is
    refreshed to current state rather than left stale.

    Issue #39: this only *requests* the Reward now (PENDING_CONFIRMATION,
    cost frozen) -- it never redeems it. An Adult confirms or rejects it
    from /confirmations (see app/telegram/handlers/confirmations.py).
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False, _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, False, _NOT_A_CHILD_TEXT, None

        success = False
        try:
            reward_id = uuid.UUID(raw_reward_id)
            redemption, reward, available_balance = request_reward_redemption(db, user, reward_id)
            notifications.notify_reward_awaiting_confirmation(db, redemption, reward, user)
            toast = render_reward_requested(reward, available_balance)
            success = True
        except (ValueError, RewardNotFoundError):
            toast = _REWARD_UNAVAILABLE_TEXT
        except InsufficientPointsError:
            toast = _INSUFFICIENT_POINTS_TEXT

        rewards, available_balance = get_rewards(db, user)
        return (
            toast,
            success,
            render_rewards(rewards, available_balance),
            rewards_keyboard(rewards, available_balance),
        )
    finally:
        db.close()


async def handle_request_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_reward_id = query.data.removeprefix(REQUEST_CALLBACK_PREFIX)
    toast, success, text, keyboard = await asyncio.to_thread(
        _request, update.effective_user.id, raw_reward_id
    )
    await query.answer(text=toast, show_alert=success)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_rewards_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reopens the existing /rewards flow (Issue: Telegram notifications)
    -- the "Награды" button on the Child "Reward confirmed" notification
    calls this, via keyboards.rewards.LIST_CALLBACK_DATA.
    """
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, keyboard = await asyncio.to_thread(_rewards_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
