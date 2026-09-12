import asyncio
import uuid
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.goal_operations import (
    GoalNotEditableError,
    GoalNotFoundError,
    InvalidGoalInputError,
    NotAnAdultError,
    create_goal,
    get_goal_details,
    get_goals,
    update_goal,
)
from app.models import GoalStatus, UserRole, utcnow
from app.telegram.handlers.goals import _goals_view as _child_goals_view
from app.telegram.handlers.start import _resolve_home
from app.telegram.keyboards.adult_goals import (
    EDIT_CALLBACK_PREFIX,
    EDIT_COST_CALLBACK_PREFIX,
    EDIT_NAME_CALLBACK_PREFIX,
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    back_to_goals_keyboard,
    decode_older_payload,
    edit_menu_keyboard,
    goal_details_keyboard,
    goals_list_keyboard,
)
from app.telegram.views.adult_goals import (
    render_create_prompt_cost,
    render_create_prompt_name,
    render_edit_menu,
    render_edit_prompt_cost,
    render_edit_prompt_name,
    render_goal_created,
    render_goal_updated,
    render_goals_list,
)
from app.telegram.views.goals import render_goal_details
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Ваш Telegram-аккаунт ещё не подключён. Попросите у взрослого, который "
    "управляет вашим аккаунтом, ссылку для активации."
)
_NOT_AN_ADULT_TEXT = "Это недоступно для вашего аккаунта."
_GOAL_NOT_FOUND_TEXT = "Цель не найдена."
_GOAL_NOT_EDITABLE_TEXT = "Эта цель уже достигнута, её нельзя редактировать."

# Per-chat, in-memory only (pattern established by Issue #28's Task
# Create/Edit flow): tracks which single text prompt, if any, is currently
# open for this Adult. Never persisted -- if the bot restarts mid-flow, the
# Adult just presses the button again; no business state depends on this.
_FLOW_KEY = "adult_goal_flow"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _adult_goals_list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goals = get_goals(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        return render_goals_list(goals), goals_list_keyboard(goals)
    finally:
        db.close()


def _goals_command_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """`/goals` is role-aware (Issue: Goals), matching `/tasks`/`/rewards`/
    `/points`: a Child's own contribution view and an Adult's management
    catalog are different screens behind the same command.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        role = user.role
    finally:
        db.close()

    if role == UserRole.ADULT:
        return _adult_goals_list_view(telegram_user_id)
    return _child_goals_view(telegram_user_id)


def _goal_details_view(
    telegram_user_id: int, raw_goal_id: str, cursor: uuid.UUID | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
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


def _start_create(telegram_user_id: int) -> tuple[str, bool]:
    """Returns (text, should_start_flow). The role check here is purely for
    a pleasant UX (don't prompt a Child for a goal name); create_goal's own
    role check is what's actually authoritative.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, False
        return render_create_prompt_name(), True
    finally:
        db.close()


def _start_edit_menu(
    telegram_user_id: int, raw_goal_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        try:
            view = get_goal_details(db, goal_id)
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        if view.goal.status != GoalStatus.ACTIVE:
            return _GOAL_NOT_EDITABLE_TEXT, back_to_goals_keyboard()
        return render_edit_menu(view.goal), edit_menu_keyboard(view.goal)
    finally:
        db.close()


def _start_edit_field(
    telegram_user_id: int, raw_goal_id: str, field: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Returns (text, keyboard-on-failure, should_start_flow)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None, False
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None, False
        try:
            goal_id = uuid.UUID(raw_goal_id)
        except ValueError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard(), False
        try:
            view = get_goal_details(db, goal_id)
        except GoalNotFoundError:
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard(), False
        if view.goal.status != GoalStatus.ACTIVE:
            return _GOAL_NOT_EDITABLE_TEXT, back_to_goals_keyboard(), False
        prompt = (
            render_edit_prompt_name(view.goal)
            if field == "name"
            else render_edit_prompt_cost(view.goal)
        )
        return prompt, None, True
    finally:
        db.close()


def _finish_create(
    telegram_user_id: int, name: str, cost_points: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goal = create_goal(db, user, name=name, cost_points=cost_points)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except InvalidGoalInputError as exc:
            return exc.message, None
        return render_goal_created(goal), back_to_goals_keyboard()
    finally:
        db.close()


def _finish_edit_name(
    telegram_user_id: int, raw_goal_id: str, name: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
            goal = update_goal(db, user, goal_id, name=name)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, GoalNotFoundError):
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        except GoalNotEditableError:
            return _GOAL_NOT_EDITABLE_TEXT, back_to_goals_keyboard()
        except InvalidGoalInputError as exc:
            return exc.message, back_to_goals_keyboard()
        return render_goal_updated(goal), back_to_goals_keyboard()
    finally:
        db.close()


def _finish_edit_cost(
    telegram_user_id: int, raw_goal_id: str, cost_points: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            goal_id = uuid.UUID(raw_goal_id)
            goal = update_goal(db, user, goal_id, cost_points=cost_points)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, GoalNotFoundError):
            return _GOAL_NOT_FOUND_TEXT, back_to_goals_keyboard()
        except GoalNotEditableError:
            return _GOAL_NOT_EDITABLE_TEXT, back_to_goals_keyboard()
        except InvalidGoalInputError as exc:
            return exc.message, back_to_goals_keyboard()
        return render_goal_updated(goal), back_to_goals_keyboard()
    finally:
        db.close()


def _parse_cost(text: str) -> tuple[int | None, str | None]:
    try:
        value = int(text.strip())
    except ValueError:
        return None, "Пожалуйста, введите целое число баллов."
    if value <= 0:
        return None, "Стоимость должна быть больше 0."
    return value, None


async def handle_goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_goals_command_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_open_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
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
    goal_id, cursor = decode_older_payload(raw)
    raw_goal_id = str(goal_id) if goal_id is not None else ""
    text, keyboard = await asyncio.to_thread(
        _goal_details_view, update.effective_user.id, raw_goal_id, cursor
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_list_goals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_adult_goals_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_goals_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard, _role = await asyncio.to_thread(_resolve_home, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_add_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, should_start = await asyncio.to_thread(_start_create, update.effective_user.id)
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "create", "step": "name"}
    if query.message is not None:
        await query.edit_message_text(text)


async def handle_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_goal_id = query.data.removeprefix(EDIT_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _start_edit_menu, update.effective_user.id, raw_goal_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_goal_id = query.data.removeprefix(EDIT_NAME_CALLBACK_PREFIX)
    text, keyboard, should_start = await asyncio.to_thread(
        _start_edit_field, update.effective_user.id, raw_goal_id, "name"
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "edit_name", "goal_id": raw_goal_id}
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_edit_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_goal_id = query.data.removeprefix(EDIT_COST_CALLBACK_PREFIX)
    text, keyboard, should_start = await asyncio.to_thread(
        _start_edit_field, update.effective_user.id, raw_goal_id, "cost"
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "edit_cost", "goal_id": raw_goal_id}
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances one narrowly-scoped, in-memory Create/Edit flow by one text
    message (Issue: Goals, mirroring Issue #28's Task Create/Edit flow) --
    not a generic conversation state machine, just "what is this Adult's
    next message for". Returns (reply text, keyboard, whether the flow is
    now finished).
    """
    text = text.strip()
    action = flow.get("action")

    if action == "create" and flow.get("step") == "name":
        if not text:
            return "Пожалуйста, введите название цели.", None, False
        flow["name"] = text
        flow["step"] = "cost"
        return render_create_prompt_cost(), None, False

    if action == "create" and flow.get("step") == "cost":
        cost_points, error = _parse_cost(text)
        if error is not None or cost_points is None:
            return error or "Пожалуйста, введите целое число баллов.", None, False
        result_text, keyboard = _finish_create(telegram_user_id, flow["name"], cost_points)
        return result_text, keyboard, True

    if action == "edit_name":
        if not text:
            return "Пожалуйста, введите название цели.", None, False
        result_text, keyboard = _finish_edit_name(telegram_user_id, flow["goal_id"], text)
        return result_text, keyboard, True

    if action == "edit_cost":
        cost_points, error = _parse_cost(text)
        if error is not None or cost_points is None:
            return error or "Пожалуйста, введите целое число баллов.", None, False
        result_text, keyboard = _finish_edit_cost(telegram_user_id, flow["goal_id"], cost_points)
        return result_text, keyboard, True

    # Unknown/stale action -- shouldn't be reachable, but never leave the
    # Adult stuck silently ignoring their input.
    return "", None, True


async def handle_goal_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Add/Edit Goal free-text interaction. A text message with no
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
