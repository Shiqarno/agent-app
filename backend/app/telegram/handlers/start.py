import asyncio

from telegram import BotCommandScopeChat, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import UserRole
from app.reward_operations import get_balance
from app.telegram.commands import commands_for_role
from app.telegram.handlers.confirmations import _list_view as _confirmation_list_view
from app.telegram_identity import (
    TelegramAccountAlreadyLinkedError,
    TelegramActivationInvalidError,
    activate_telegram_identity,
    resolve_user_by_telegram_id,
)

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_INVALID_ACTIVATION_TEXT = (
    "This activation link is no longer valid. Ask the adult who manages your account for a new one."
)
_ALREADY_LINKED_TEXT = "This Telegram account is already connected to a different profile."


def _activate(raw_token: str, telegram_user_id: int) -> tuple[str, UserRole | None]:
    """Sync DB work run off the bot's event loop via asyncio.to_thread (see
    handle_start) -- this project's DB layer is synchronous SQLAlchemy, and
    there's no FastAPI-style per-request dependency injection here, so each
    call opens and closes its own Session, exactly one unit of work.

    The returned role (Issue #35) is presentation-only signal for the
    caller to set this chat's native command menu -- never a second
    authorization mechanism; every command handler still re-resolves the
    User itself.
    """
    db = SessionLocal()
    try:
        user = activate_telegram_identity(db, raw_token, telegram_user_id)
        return f"You're connected, {user.name}! You can now use this bot.", user.role
    except TelegramActivationInvalidError:
        return _INVALID_ACTIVATION_TEXT, None
    except TelegramAccountAlreadyLinkedError:
        return _ALREADY_LINKED_TEXT, None
    finally:
        db.close()


def _resolve_home(
    telegram_user_id: int,
) -> tuple[str, InlineKeyboardMarkup | None, UserRole | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None, None
        role = user.role
        name = user.name
        # Reuses the same shared Point Ledger query every other balance
        # display in the app uses (Issue #36) -- no Telegram-specific
        # balance calculation.
        balance = get_balance(db, user.id) if role == UserRole.CHILD else None
    finally:
        db.close()

    if role == UserRole.CHILD:
        text = (
            f"Твои баллы: 💰 {balance}\n\n"
            f"Welcome back, {name}! Use /tasks to see available tasks, "
            "/mytasks to see what you're working on, /rewards to spend your points, "
            "or /points to see your balance and history."
        )
        return text, None, role

    # Adult Home *is* the Confirmation queue (Issue #36) -- the exact same
    # retrieval and presentation `/confirmations` itself uses, not a
    # second, parallel implementation of it.
    text, keyboard = _confirmation_list_view(telegram_user_id)
    return text, keyboard, role


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/start` and `/start <activation_token>` (Issue #23). All business
    logic lives in app.telegram_identity -- this handler only extracts the
    Telegram-specific bits (the sender's id, the command argument) and
    turns the result into a reply. No task/reward/points rules here.

    Also (re)sets this chat's native Telegram command menu to match the
    resolved role (Issue #35) -- `/start` is the one place role is always
    freshly resolved for every connected User (both on first activation
    and every subsequent Home visit), so it's the natural, single hook for
    this without adding a network call to every other handler.
    """
    if update.effective_user is None or update.message is None:
        return
    telegram_user_id = update.effective_user.id

    if context.args:
        reply, role = await asyncio.to_thread(_activate, context.args[0], telegram_user_id)
        await update.message.reply_text(reply)
    else:
        text, keyboard, role = await asyncio.to_thread(_resolve_home, telegram_user_id)
        await update.message.reply_text(text, reply_markup=keyboard)

    if role is not None:
        await context.bot.set_my_commands(
            commands_for_role(role), scope=BotCommandScopeChat(chat_id=telegram_user_id)
        )
