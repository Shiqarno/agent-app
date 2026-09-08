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
    redeem_reward,
)
from app.telegram.keyboards.rewards import GET_CALLBACK_PREFIX, rewards_keyboard
from app.telegram.views.rewards import render_redemption_success, render_rewards
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_A_CHILD_TEXT = "This isn't available for your account."
_REWARD_UNAVAILABLE_TEXT = "This reward is no longer available."
_INSUFFICIENT_POINTS_TEXT = "Not enough points."


def _rewards_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        # Rewards redemption is a Child workflow in Telegram (Issue #26
        # Authorization) -- a presentation-level choice, not a new
        # Application-layer role rule: app.reward_operations mirrors the
        # existing Web endpoints, which have no role restriction.
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, None
        rewards, balance = get_rewards(db, user)
        return render_rewards(rewards, balance), rewards_keyboard(rewards, balance)
    finally:
        db.close()


def _redeem(
    telegram_user_id: int, raw_reward_id: str
) -> tuple[str, bool, str, InlineKeyboardMarkup | None]:
    """Returns (toast text, whether it was a success, refreshed Rewards
    message text, refreshed keyboard). A stale/invalid Get is handled the
    same way as any other rejection (Issue #26 "Stale Telegram
    interaction"): the Application operation is called anyway, its
    rejection becomes a friendly toast, and the view underneath is
    refreshed to current state rather than left stale.
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
            _, reward, remaining_balance = redeem_reward(db, user, reward_id)
            toast = render_redemption_success(reward, remaining_balance)
            success = True
        except (ValueError, RewardNotFoundError):
            toast = _REWARD_UNAVAILABLE_TEXT
        except InsufficientPointsError:
            toast = _INSUFFICIENT_POINTS_TEXT

        rewards, balance = get_rewards(db, user)
        return toast, success, render_rewards(rewards, balance), rewards_keyboard(rewards, balance)
    finally:
        db.close()


async def handle_get_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_reward_id = query.data.removeprefix(GET_CALLBACK_PREFIX)
    toast, success, text, keyboard = await asyncio.to_thread(
        _redeem, update.effective_user.id, raw_reward_id
    )
    await query.answer(text=toast, show_alert=success)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
