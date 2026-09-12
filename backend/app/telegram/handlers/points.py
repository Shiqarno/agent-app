import asyncio
import uuid

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import UserRole, utcnow
from app.points_operations import get_points
from app.telegram.keyboards.points import OLDER_CALLBACK_PREFIX, points_keyboard
from app.telegram.views.points import render_points
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_A_CHILD_TEXT = "Это недоступно для вашего аккаунта."


def _points_view(
    telegram_user_id: int, cursor: uuid.UUID | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        # Adult Points UX is a separate management workflow, dispatched by
        # `/points`'s role-aware handler in adult_points.py (Issue #31) --
        # this function stays the Child-only self-service view, reused
        # from there for the Child branch. A presentation-level choice
        # here, not a new Application-layer rule: get_points already
        # scopes strictly to the resolved User regardless of role.
        if user.role != UserRole.CHILD:
            return _NOT_A_CHILD_TEXT, None
        view = get_points(db, user, cursor=cursor)
        return render_points(view, utcnow()), points_keyboard(view)
    finally:
        db.close()


async def handle_older_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_cursor = query.data.removeprefix(OLDER_CALLBACK_PREFIX)
    try:
        cursor: uuid.UUID | None = uuid.UUID(raw_cursor)
    except ValueError:
        # A stale/malformed cursor gracefully falls back to the first page
        # (Issue #27 "Stale/invalid cursor") rather than erroring.
        cursor = None
    text, keyboard = await asyncio.to_thread(_points_view, update.effective_user.id, cursor)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
