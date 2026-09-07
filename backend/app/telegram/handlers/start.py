import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import UserRole
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


def _activate(raw_token: str, telegram_user_id: int) -> str:
    """Sync DB work run off the bot's event loop via asyncio.to_thread (see
    handle_start) -- this project's DB layer is synchronous SQLAlchemy, and
    there's no FastAPI-style per-request dependency injection here, so each
    call opens and closes its own Session, exactly one unit of work.
    """
    db = SessionLocal()
    try:
        user = activate_telegram_identity(db, raw_token, telegram_user_id)
        return f"You're connected, {user.name}! You can now use this bot."
    except TelegramActivationInvalidError:
        return _INVALID_ACTIVATION_TEXT
    except TelegramAccountAlreadyLinkedError:
        return _ALREADY_LINKED_TEXT
    finally:
        db.close()


def _resolve_home(telegram_user_id: int) -> str:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT
        # Minimal, role-aware placeholder -- Reward/Points UX and a full
        # Adult workflow are still out of scope (Issue #24 implements only
        # the Child Tasks/My Tasks navigation below).
        if user.role == UserRole.CHILD:
            return (
                f"Welcome back, {user.name}! Use /tasks to see available tasks, "
                "or /mytasks to see what you're working on."
            )
        return f"Welcome back, {user.name}! Your Telegram account is connected."
    finally:
        db.close()


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/start` and `/start <activation_token>` (Issue #23). All business
    logic lives in app.telegram_identity -- this handler only extracts the
    Telegram-specific bits (the sender's id, the command argument) and
    turns the result into a reply. No task/reward/points rules here.
    """
    if update.effective_user is None or update.message is None:
        return
    telegram_user_id = update.effective_user.id

    if context.args:
        reply = await asyncio.to_thread(_activate, context.args[0], telegram_user_id)
    else:
        reply = await asyncio.to_thread(_resolve_home, telegram_user_id)

    await update.message.reply_text(reply)
