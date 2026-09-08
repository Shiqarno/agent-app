import asyncio
import uuid
from typing import Any

from sqlalchemy.orm import Session
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import User, UserRole, utcnow
from app.points_operations import (
    InsufficientBalanceError,
    InvalidAdjustmentError,
    NotAuthorizedError,
    adjust_points,
    get_points,
)
from app.reward_operations import get_balance
from app.telegram.handlers.points import _points_view as _child_points_self_view
from app.telegram.handlers.start import _resolve_home
from app.telegram.keyboards.adult_points import (
    ADD_CALLBACK_PREFIX,
    ADJUST_CALLBACK_PREFIX,
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    REMOVE_CALLBACK_PREFIX,
    adjust_menu_keyboard,
    back_to_children_keyboard,
    child_points_keyboard,
    points_children_keyboard,
)
from app.telegram.views.adult_points import (
    render_adjust_menu,
    render_adjustment_success,
    render_amount_prompt,
    render_child_points,
    render_children_points_list,
    render_description_prompt,
    render_insufficient_balance,
)
from app.telegram_identity import resolve_user_by_telegram_id
from app.user_operations import get_users

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_AN_ADULT_TEXT = "This isn't available for your account."
_CHILD_NOT_FOUND_TEXT = "Child not found."

# Per-chat, in-memory only (pattern established by Issues #29/#30): tracks
# which step of the Adjust Points flow this Adult is currently on. Never
# persisted -- if the bot restarts mid-flow, the Adult just starts again;
# no business state depends on this, and the Point balance itself is never
# stored here, only re-read fresh from the ledger on every step.
_FLOW_KEY = "adult_points_flow"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _children_list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, None
        if actor.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        users = get_users(db, actor)
        children = [user for user, _connected in users if user.role == UserRole.CHILD]
        items = [(child, get_balance(db, child.id)) for child in children]
        return render_children_points_list(items), points_children_keyboard(items)
    finally:
        db.close()


def _resolve_child(db: Session, raw_child_id: str) -> User | None:
    try:
        child_id = uuid.UUID(raw_child_id)
    except ValueError:
        return None
    child = db.get(User, child_id)
    if child is None or child.role != UserRole.CHILD:
        return None
    return child


def _child_points_view(
    telegram_user_id: int, raw_child_id: str, cursor: uuid.UUID | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, None
        if actor.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        child = _resolve_child(db, raw_child_id)
        if child is None:
            return _CHILD_NOT_FOUND_TEXT, back_to_children_keyboard()
        view = get_points(db, actor, target_user=child, cursor=cursor)
        return render_child_points(child, view, utcnow()), child_points_keyboard(child.id, view)
    finally:
        db.close()


def _adjust_menu_view(
    telegram_user_id: int, raw_child_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, None
        if actor.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        child = _resolve_child(db, raw_child_id)
        if child is None:
            return _CHILD_NOT_FOUND_TEXT, back_to_children_keyboard()
        balance = get_balance(db, child.id)
        return render_adjust_menu(child, balance), adjust_menu_keyboard(child.id)
    finally:
        db.close()


def _start_adjust(
    telegram_user_id: int, raw_child_id: str, direction: str
) -> tuple[str, bool, InlineKeyboardMarkup | None]:
    """Returns (text, should_start_flow, keyboard-on-failure)."""
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, False, None
        if actor.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, False, None
        child = _resolve_child(db, raw_child_id)
        if child is None:
            return _CHILD_NOT_FOUND_TEXT, False, back_to_children_keyboard()
        return render_amount_prompt(direction, child), True, None
    finally:
        db.close()


def _finish_adjust(
    telegram_user_id: int, raw_child_id: str, direction: str, magnitude: int, description: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, None
        child = _resolve_child(db, raw_child_id)
        if child is None:
            return _CHILD_NOT_FOUND_TEXT, back_to_children_keyboard()

        signed_amount = magnitude if direction == "add" else -magnitude
        try:
            _transaction, new_balance = adjust_points(
                db, actor, child, amount=signed_amount, description=description
            )
        except NotAuthorizedError:
            return _NOT_AN_ADULT_TEXT, None
        except InsufficientBalanceError:
            balance = get_balance(db, child.id)
            return (
                render_insufficient_balance(child, magnitude, balance),
                child_points_keyboard(child.id, get_points(db, actor, target_user=child)),
            )
        except InvalidAdjustmentError as exc:
            return exc.message, None

        view = get_points(db, actor, target_user=child)
        text = (
            render_adjustment_success(child, signed_amount, new_balance)
            + "\n\n"
            + render_child_points(child, view, utcnow())
        )
        return text, child_points_keyboard(child.id, view)
    finally:
        db.close()


def _parse_magnitude(text: str) -> tuple[int | None, str | None]:
    try:
        value = int(text.strip())
    except ValueError:
        return None, "Please enter a whole number of points."
    if value <= 0:
        return None, "Amount must be greater than 0."
    return value, None


def _points_command_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """`/points` is role-aware (Issue #31, matching Issue #28's `/tasks` and
    Issue #30's `/rewards` precedent): a Child's own self-service Points
    view and an Adult's Points management view are different screens
    behind the same command, dispatched by the connected User's role.
    """
    db = SessionLocal()
    try:
        actor = resolve_user_by_telegram_id(db, telegram_user_id)
        if actor is None:
            return _NOT_CONNECTED_TEXT, None
        role = actor.role
    finally:
        db.close()

    if role == UserRole.ADULT:
        return _children_list_view(telegram_user_id)
    return _child_points_self_view(telegram_user_id, None)


async def handle_points_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_points_command_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_list_children(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_children_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_points_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard, _role = await asyncio.to_thread(_resolve_home, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_open_child_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_child_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _child_points_view, update.effective_user.id, raw_child_id, None
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_older_child_points(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw = query.data.removeprefix(OLDER_CALLBACK_PREFIX)
    raw_child_id, _, raw_cursor = raw.partition(":")
    try:
        cursor: uuid.UUID | None = uuid.UUID(raw_cursor)
    except ValueError:
        # A stale/malformed cursor gracefully falls back to the first page
        # (matching the Child Points precedent) rather than erroring.
        cursor = None
    text, keyboard = await asyncio.to_thread(
        _child_points_view, update.effective_user.id, raw_child_id, cursor
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_adjust_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_child_id = query.data.removeprefix(ADJUST_CALLBACK_PREFIX)
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(
        _adjust_menu_view, update.effective_user.id, raw_child_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def _handle_start_direction(
    update: Update, context: ContextTypes.DEFAULT_TYPE, prefix: str, direction: str
) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_child_id = query.data.removeprefix(prefix)
    text, should_start, keyboard = await asyncio.to_thread(
        _start_adjust, update.effective_user.id, raw_child_id, direction
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {
            "direction": direction,
            "step": "amount",
            "child_id": raw_child_id,
        }
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_start_direction(update, context, ADD_CALLBACK_PREFIX, "add")


async def handle_start_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _handle_start_direction(update, context, REMOVE_CALLBACK_PREFIX, "remove")


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances one narrowly-scoped, in-memory Adjust Points flow by one
    text message. Returns (reply text, keyboard, whether the flow is now
    finished). Not a generic conversation state machine -- two fixed
    steps, amount -> description, for both add and remove.
    """
    text = text.strip()
    direction = flow.get("direction")
    if direction not in ("add", "remove"):
        # Unknown/stale direction -- shouldn't be reachable, but never
        # leave the Adult stuck silently ignoring their input.
        return "", None, True

    step = flow.get("step")

    if step == "amount":
        magnitude, error = _parse_magnitude(text)
        if error is not None or magnitude is None:
            return error or "Please enter a whole number of points.", None, False
        flow["magnitude"] = magnitude
        flow["step"] = "description"
        return render_description_prompt(direction), None, False

    if step == "description":
        if not text:
            return "Please enter a description.", None, False
        result_text, keyboard = _finish_adjust(
            telegram_user_id, flow["child_id"], direction, flow["magnitude"], text
        )
        return result_text, keyboard, True

    return "", None, True


async def handle_points_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Adjust Points free-text interaction. A text message with no
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
