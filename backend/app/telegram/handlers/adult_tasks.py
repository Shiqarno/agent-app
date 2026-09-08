import asyncio
import uuid
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import User, UserRole
from app.task_operations import (
    ChildNotFoundError,
    InvalidTaskInputError,
    NotAnAdultError,
    TaskAlreadyOpenForChildError,
    TaskNotEditableError,
    TaskNotFoundError,
    activate_task,
    assign_task,
    create_task,
    deactivate_task,
    get_assignable_children,
    get_task,
    get_tasks,
    update_task,
)
from app.telegram.handlers.start import _resolve_home
from app.telegram.handlers.tasks import _tasks_view
from app.telegram.keyboards.adult_tasks import (
    ACTIVATE_CALLBACK_PREFIX,
    ASSIGN_CALLBACK_PREFIX,
    ASSIGN_TO_CALLBACK_PREFIX,
    DEACTIVATE_CALLBACK_PREFIX,
    EDIT_CALLBACK_PREFIX,
    EDIT_NAME_CALLBACK_PREFIX,
    EDIT_REWARD_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    assign_children_keyboard,
    back_to_tasks_keyboard,
    edit_menu_keyboard,
    task_details_keyboard,
    tasks_list_keyboard,
)
from app.telegram.views.adult_tasks import (
    render_assign_children,
    render_create_prompt_reward,
    render_create_prompt_title,
    render_edit_menu,
    render_edit_prompt_reward,
    render_edit_prompt_title,
    render_task_assigned,
    render_task_details,
    render_tasks_list,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_AN_ADULT_TEXT = "This isn't available for your account."
_TASK_NOT_FOUND_TEXT = "Task not found."
_TASK_NOT_EDITABLE_TEXT = (
    "This task cannot be edited while it is being worked on. Please open Tasks again."
)
_CHILD_NOT_FOUND_TEXT = "Child not found."
_ALREADY_OPEN_TEXT = "This child already has an open execution of this task."

# Per-chat, in-memory only (Issue #28 section 14): tracks which single text
# prompt, if any, is currently open for this Adult ("what's the next text
# message for"). Never persisted -- if the bot restarts mid-flow, the Adult
# just presses the button again; no business state depends on this.
_FLOW_KEY = "adult_task_flow"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _adult_tasks_list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            items = get_tasks(db, user)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        return render_tasks_list(items), tasks_list_keyboard(items)
    finally:
        db.close()


def _tasks_command_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """`/tasks` is role-aware (Issue #28): a Child's Tasks (available to
    claim) and an Adult's Tasks (the definition catalog) are different
    screens behind the same command, matching how `/start` already
    dispatches Home by role.
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
        return _adult_tasks_list_view(telegram_user_id)
    return _tasks_view(telegram_user_id)


def _task_details_view(
    telegram_user_id: int, raw_task_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        try:
            task, execution, child = get_task(db, user, task_id)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        return render_task_details(task, execution, child), task_details_keyboard(
            task, execution is not None
        )
    finally:
        db.close()


def _start_create(telegram_user_id: int) -> tuple[str, bool]:
    """Returns (text, should_start_flow). The role check here is purely for
    a pleasant UX (don't prompt a Child for a task name); create_task's own
    role check is what's actually authoritative.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, False
        return render_create_prompt_title(), True
    finally:
        db.close()


def _start_edit_menu(
    telegram_user_id: int, raw_task_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        try:
            task, execution, _child = get_task(db, user, task_id)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        if execution is not None:
            return _TASK_NOT_EDITABLE_TEXT, back_to_tasks_keyboard()
        return render_edit_menu(task), edit_menu_keyboard(task)
    finally:
        db.close()


def _start_edit_field(
    telegram_user_id: int, raw_task_id: str, field: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Returns (text, keyboard-on-failure, should_start_flow)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None, False
        try:
            task_id = uuid.UUID(raw_task_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard(), False
        try:
            task, execution, _child = get_task(db, user, task_id)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None, False
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard(), False
        if execution is not None:
            return _TASK_NOT_EDITABLE_TEXT, back_to_tasks_keyboard(), False
        prompt = (
            render_edit_prompt_title(task) if field == "title" else render_edit_prompt_reward(task)
        )
        return prompt, None, True
    finally:
        db.close()


def _finish_create(
    telegram_user_id: int, title: str, reward_points: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task = create_task(db, user, title=title, reward_points=reward_points)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except InvalidTaskInputError as exc:
            return exc.message, None
        return render_task_details(task, None, None), task_details_keyboard(task, False)
    finally:
        db.close()


def _finish_edit_title(
    telegram_user_id: int, raw_task_id: str, title: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
            task = update_task(db, user, task_id, title=title)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, TaskNotFoundError):
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        except TaskNotEditableError:
            return _TASK_NOT_EDITABLE_TEXT, back_to_tasks_keyboard()
        except InvalidTaskInputError as exc:
            return exc.message, back_to_tasks_keyboard()
        return render_task_details(task, None, None), task_details_keyboard(task, False)
    finally:
        db.close()


def _finish_edit_reward(
    telegram_user_id: int, raw_task_id: str, reward_points: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
            task = update_task(db, user, task_id, reward_points=reward_points)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, TaskNotFoundError):
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        except TaskNotEditableError:
            return _TASK_NOT_EDITABLE_TEXT, back_to_tasks_keyboard()
        except InvalidTaskInputError as exc:
            return exc.message, back_to_tasks_keyboard()
        return render_task_details(task, None, None), task_details_keyboard(task, False)
    finally:
        db.close()


def _toggle_active(
    telegram_user_id: int, raw_task_id: str, *, activate: bool
) -> tuple[str, str, InlineKeyboardMarkup | None]:
    """Returns (toast, refreshed message text, refreshed keyboard). Never
    blocked by a current open execution (Issue #37: `is_active` is a
    self-claim slot, independent of whatever executions already exist) --
    the only rejections left are role and existence.
    """
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, _NOT_CONNECTED_TEXT, None

        try:
            task_id = uuid.UUID(raw_task_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()

        try:
            task = (
                activate_task(db, user, task_id) if activate else deactivate_task(db, user, task_id)
            )
            toast = f"{task.title} activated." if activate else f"{task.title} deactivated."
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, _NOT_AN_ADULT_TEXT, None
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()

        try:
            task, execution, child = get_task(db, user, task_id)
        except TaskNotFoundError:
            return toast, _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        return (
            toast,
            render_task_details(task, execution, child),
            task_details_keyboard(task, execution is not None),
        )
    finally:
        db.close()


def _assign_menu_view(
    telegram_user_id: int, raw_task_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        try:
            task, _execution, _child = get_task(db, user, task_id)
            children = get_assignable_children(db, user, task_id)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        return render_assign_children(task, children), assign_children_keyboard(task.id, children)
    finally:
        db.close()


def _finish_assign(
    telegram_user_id: int, raw_task_id: str, raw_child_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            task_id = uuid.UUID(raw_task_id)
            child_id = uuid.UUID(raw_child_id)
        except ValueError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()

        child = db.get(User, child_id)
        if child is None:
            return _CHILD_NOT_FOUND_TEXT, back_to_tasks_keyboard()

        try:
            _execution, task = assign_task(db, user, task_id, child)
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except TaskNotFoundError:
            return _TASK_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        except ChildNotFoundError:
            return _CHILD_NOT_FOUND_TEXT, back_to_tasks_keyboard()
        except TaskAlreadyOpenForChildError:
            return _ALREADY_OPEN_TEXT, back_to_tasks_keyboard()

        task, execution, _current_child = get_task(db, user, task.id)
        return render_task_assigned(task, child), task_details_keyboard(task, execution is not None)
    finally:
        db.close()


def _parse_reward_points(text: str) -> tuple[int | None, str | None]:
    try:
        value = int(text.strip())
    except ValueError:
        return None, "Please enter a whole number of points."
    if value <= 0:
        return None, "Points must be greater than 0."
    return value, None


async def handle_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_tasks_command_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_open_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _task_details_view, update.effective_user.id, raw_task_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_adult_tasks_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard, _role = await asyncio.to_thread(_resolve_home, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, should_start = await asyncio.to_thread(_start_create, update.effective_user.id)
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "create", "step": "title"}
    if query.message is not None:
        await query.edit_message_text(text)


async def handle_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(EDIT_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _start_edit_menu, update.effective_user.id, raw_task_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(EDIT_NAME_CALLBACK_PREFIX)
    text, keyboard, should_start = await asyncio.to_thread(
        _start_edit_field, update.effective_user.id, raw_task_id, "title"
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "edit_title", "task_id": raw_task_id}
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_edit_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(EDIT_REWARD_CALLBACK_PREFIX)
    text, keyboard, should_start = await asyncio.to_thread(
        _start_edit_field, update.effective_user.id, raw_task_id, "reward"
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "edit_reward", "task_id": raw_task_id}
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_activate_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(ACTIVATE_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _toggle_active, update.effective_user.id, raw_task_id, activate=True
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_deactivate_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(DEACTIVATE_CALLBACK_PREFIX)
    toast, text, keyboard = await asyncio.to_thread(
        _toggle_active, update.effective_user.id, raw_task_id, activate=False
    )
    await query.answer(text=toast)
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_assign_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_task_id = query.data.removeprefix(ASSIGN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _assign_menu_view, update.effective_user.id, raw_task_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_assign_to_child(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw = query.data.removeprefix(ASSIGN_TO_CALLBACK_PREFIX)
    raw_task_id, _, raw_child_id = raw.partition(":")
    text, keyboard = await asyncio.to_thread(
        _finish_assign, update.effective_user.id, raw_task_id, raw_child_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances one narrowly-scoped, in-memory Create/Edit flow by one text
    message (Issue #28 section 14) -- not a generic conversation state
    machine, just "what is this Adult's next message for". Returns (reply
    text, keyboard, whether the flow is now finished). Mutates `flow` in
    place for a same-flow step transition (create's title -> reward); the
    caller clears it from `context.user_data` once finished is True.
    """
    text = text.strip()
    action = flow.get("action")

    if action == "create" and flow.get("step") == "title":
        if not text:
            return "Please enter a task name.", None, False
        flow["title"] = text
        flow["step"] = "reward"
        return render_create_prompt_reward(), None, False

    if action == "create" and flow.get("step") == "reward":
        reward_points, error = _parse_reward_points(text)
        if error is not None or reward_points is None:
            return error or "Please enter a whole number of points.", None, False
        result_text, keyboard = _finish_create(telegram_user_id, flow["title"], reward_points)
        return result_text, keyboard, True

    if action == "edit_title":
        if not text:
            return "Please enter a task name.", None, False
        result_text, keyboard = _finish_edit_title(telegram_user_id, flow["task_id"], text)
        return result_text, keyboard, True

    if action == "edit_reward":
        reward_points, error = _parse_reward_points(text)
        if error is not None or reward_points is None:
            return error or "Please enter a whole number of points.", None, False
        result_text, keyboard = _finish_edit_reward(
            telegram_user_id, flow["task_id"], reward_points
        )
        return result_text, keyboard, True

    # Unknown/stale action -- shouldn't be reachable, but never leave the
    # Adult stuck silently ignoring their input.
    return "", None, True


async def handle_task_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The only free-text interaction in the bot (Issue #28 section 14). A
    text message with no active flow is silently ignored.
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
