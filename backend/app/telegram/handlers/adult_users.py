import asyncio
import uuid
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import UserRole
from app.telegram.handlers.start import _resolve_home
from app.telegram.keyboards.users import (
    GET_LINK_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    back_to_users_keyboard,
    user_details_keyboard,
    users_list_keyboard,
)
from app.telegram.views.users import (
    render_activation_link,
    render_add_child_prompt,
    render_child_created,
    render_user_details,
    render_users_list,
)
from app.telegram_identity import resolve_user_by_telegram_id
from app.user_operations import (
    InvalidNameError,
    NotAnAdultError,
    UserAlreadyConnectedError,
    UserNotFoundError,
    create_child,
    generate_activation_token,
    get_users,
)

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_AN_ADULT_TEXT = "Это недоступно для вашего аккаунта."
_USER_NOT_FOUND_TEXT = "Пользователь не найден."
_ALREADY_CONNECTED_TEXT = "Этот пользователь уже подключён к Telegram."

# Per-chat, in-memory only (Issue #29 section on short-lived Telegram input
# state): tracks that the next text message from this Adult is the new
# Child's name. Never persisted -- if the bot restarts mid-flow, the Adult
# just presses "+ Add Child" again; no business state depends on this.
_FLOW_KEY = "adult_user_flow"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _build_activation_link(bot_username: str, token: str) -> str:
    """Telegram deep-link construction is adapter/presentation responsibility
    (Issue #29 section 4) -- the Application layer only ever deals with the
    raw activation token.
    """
    return f"https://t.me/{bot_username}?start={token}"


def _users_list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_users(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        return render_users_list(items), users_list_keyboard(items)
    finally:
        db.close()


def _user_details_view(
    telegram_user_id: int, raw_target_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        try:
            target_id = uuid.UUID(raw_target_id)
        except ValueError:
            return _USER_NOT_FOUND_TEXT, back_to_users_keyboard()

        try:
            items = get_users(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        match = next((item for item in items if item[0].id == target_id), None)
        if match is None:
            return _USER_NOT_FOUND_TEXT, back_to_users_keyboard()
        target, connected = match
        return render_user_details(target, connected), user_details_keyboard(target, connected)
    finally:
        db.close()


def _start_add_child(telegram_user_id: int) -> tuple[str, bool]:
    """Returns (text, should_start_flow). The role check here is purely for
    a pleasant UX (don't prompt a Child for a name); create_child's own
    role check is what's actually authoritative.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, False
        return render_add_child_prompt(), True
    finally:
        db.close()


def _finish_add_child(
    telegram_user_id: int, name: str, bot_username: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            child, token = create_child(db, user, name=name)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except InvalidNameError as exc:
            return exc.message, None
        link = _build_activation_link(bot_username, token)
        return render_child_created(child.name, link), user_details_keyboard(child, False)
    finally:
        db.close()


def _finish_get_link(
    telegram_user_id: int, raw_target_id: str, bot_username: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    """A stale/invalid action (Issue #29 Callback Security) is handled the
    same way as any other rejection: the Application operation is called
    anyway, its rejection becomes a friendly message, and the user is left
    with a way back rather than stranded.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None

        try:
            target_id = uuid.UUID(raw_target_id)
            token = generate_activation_token(db, user, target_id)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, UserNotFoundError):
            return _USER_NOT_FOUND_TEXT, back_to_users_keyboard()
        except UserAlreadyConnectedError:
            return _ALREADY_CONNECTED_TEXT, back_to_users_keyboard()

        link = _build_activation_link(bot_username, token)
        return render_activation_link(link), back_to_users_keyboard()
    finally:
        db.close()


async def handle_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_users_list_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_open_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_target_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _user_details_view, update.effective_user.id, raw_target_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_users_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_users_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard, _role = await asyncio.to_thread(_resolve_home, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_add_child(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, should_start = await asyncio.to_thread(_start_add_child, update.effective_user.id)
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "add_child"}
    if query.message is not None:
        await query.edit_message_text(text)


async def handle_get_activation_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_target_id = query.data.removeprefix(GET_LINK_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _finish_get_link, update.effective_user.id, raw_target_id, context.bot.username or ""
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str, bot_username: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances the one narrowly-scoped, in-memory Add Child flow by one
    text message. Returns (reply text, keyboard, whether the flow is now
    finished). Not a generic conversation state machine -- there is exactly
    one step.
    """
    text = text.strip()
    if flow.get("action") == "add_child":
        if not text:
            return "Пожалуйста, введите имя.", None, False
        result_text, keyboard = _finish_add_child(telegram_user_id, text, bot_username)
        return result_text, keyboard, True

    # Unknown/stale action -- shouldn't be reachable, but never leave the
    # Adult stuck silently ignoring their input.
    return "", None, True


async def handle_user_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Add Child free-text interaction. A text message with no active
    flow is silently ignored.
    """
    if update.effective_user is None or update.message is None or update.message.text is None:
        return
    data = _user_data(context)
    flow = data.get(_FLOW_KEY)
    if not flow:
        return

    text, keyboard, finished = await asyncio.to_thread(
        _route_flow_text,
        update.effective_user.id,
        flow,
        update.message.text,
        context.bot.username or "",
    )
    if finished:
        data.pop(_FLOW_KEY, None)
    if text:
        await update.message.reply_text(text, reply_markup=keyboard)
