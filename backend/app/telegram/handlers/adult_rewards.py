import asyncio
import uuid
from typing import Any

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.db import SessionLocal
from app.models import Reward, UserRole
from app.reward_operations import (
    InvalidRewardInputError,
    NotAnAdultError,
    RewardNotFoundError,
    create_reward,
    get_rewards,
    update_reward,
)
from app.telegram.handlers.rewards import _rewards_view as _child_rewards_view
from app.telegram.handlers.start import _resolve_home
from app.telegram.keyboards.adult_rewards import (
    EDIT_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    back_to_rewards_keyboard,
    reward_details_keyboard,
    rewards_list_keyboard,
)
from app.telegram.views.adult_rewards import (
    render_create_prompt_cost,
    render_create_prompt_description,
    render_create_prompt_name,
    render_edit_prompt_cost,
    render_edit_prompt_description,
    render_edit_prompt_name,
    render_reward_created,
    render_reward_details,
    render_reward_updated,
    render_rewards_list,
)
from app.telegram_identity import resolve_user_by_telegram_id

_NOT_CONNECTED_TEXT = (
    "Your Telegram account isn't connected yet. Ask the adult who manages "
    "your account for an activation link."
)
_NOT_AN_ADULT_TEXT = "This isn't available for your account."
_REWARD_NOT_FOUND_TEXT = "Reward not found."

# Per-chat, in-memory only (pattern established by Issue #29): tracks which
# step of the Add/Edit Reward flow this Adult is currently on. Never
# persisted -- if the bot restarts mid-flow, the Adult just starts again;
# no business state depends on this.
_FLOW_KEY = "adult_reward_flow"

_SKIP_KEYWORD = "skip"


def _user_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    data = context.user_data
    return data if data is not None else {}


def _rewards_list_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        rewards, _balance = get_rewards(db, user)
        return render_rewards_list(rewards), rewards_list_keyboard(rewards)
    finally:
        db.close()


def _reward_details_view(
    telegram_user_id: int, raw_reward_id: str
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, None
        try:
            reward_id = uuid.UUID(raw_reward_id)
        except ValueError:
            return _REWARD_NOT_FOUND_TEXT, back_to_rewards_keyboard()
        reward = db.get(Reward, reward_id)
        if reward is None:
            return _REWARD_NOT_FOUND_TEXT, back_to_rewards_keyboard()
        return render_reward_details(reward), reward_details_keyboard(reward)
    finally:
        db.close()


def _start_create(telegram_user_id: int) -> tuple[str, bool]:
    """Returns (text, should_start_flow). The role check here is purely for
    a pleasant UX; create_reward's own role check is what's authoritative.
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


def _start_edit(
    telegram_user_id: int, raw_reward_id: str
) -> tuple[str, bool, InlineKeyboardMarkup | None]:
    """Returns (text, should_start_flow, keyboard-on-failure)."""
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, False, None
        if user.role != UserRole.ADULT:
            return _NOT_AN_ADULT_TEXT, False, None
        try:
            reward_id = uuid.UUID(raw_reward_id)
        except ValueError:
            return _REWARD_NOT_FOUND_TEXT, False, back_to_rewards_keyboard()
        reward = db.get(Reward, reward_id)
        if reward is None:
            return _REWARD_NOT_FOUND_TEXT, False, back_to_rewards_keyboard()
        return render_edit_prompt_name(reward), True, None
    finally:
        db.close()


def _finish_create(
    telegram_user_id: int, name: str, cost_points: int, description: str | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            reward = create_reward(
                db, user, name=name, description=description, cost_points=cost_points
            )
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except InvalidRewardInputError as exc:
            return exc.message, None
        return render_reward_created(reward), reward_details_keyboard(reward)
    finally:
        db.close()


def _finish_edit(
    telegram_user_id: int,
    raw_reward_id: str,
    name: str,
    cost_points: int,
    description: str | None,
) -> tuple[str, InlineKeyboardMarkup | None]:
    db = SessionLocal()
    try:
        user = resolve_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            return _NOT_CONNECTED_TEXT, None
        try:
            reward_id = uuid.UUID(raw_reward_id)
            reward = update_reward(
                db,
                user,
                reward_id,
                name=name,
                description=description,
                cost_points=cost_points,
            )
        except NotAnAdultError:
            return _NOT_AN_ADULT_TEXT, None
        except (ValueError, RewardNotFoundError):
            return _REWARD_NOT_FOUND_TEXT, back_to_rewards_keyboard()
        except InvalidRewardInputError as exc:
            return exc.message, back_to_rewards_keyboard()
        return render_reward_updated(reward), reward_details_keyboard(reward)
    finally:
        db.close()


def _parse_cost(text: str) -> tuple[int | None, str | None]:
    try:
        value = int(text.strip())
    except ValueError:
        return None, "Please enter a whole number of points."
    if value <= 0:
        return None, "Cost must be greater than 0."
    return value, None


def _rewards_command_view(telegram_user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """`/rewards` is role-aware (Issue #30, matching Issue #28's `/tasks`
    precedent): a Child's Rewards (redeem with points) and an Adult's
    Rewards (catalog management) are different screens behind the same
    command, dispatched by the connected User's role.
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
        return _rewards_list_view(telegram_user_id)
    return _child_rewards_view(telegram_user_id)


async def handle_rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.message is None:
        return
    text, keyboard = await asyncio.to_thread(_rewards_command_view, update.effective_user.id)
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_open_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_reward_id = query.data.removeprefix(OPEN_CALLBACK_PREFIX)
    text, keyboard = await asyncio.to_thread(
        _reward_details_view, update.effective_user.id, raw_reward_id
    )
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_list_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_rewards_list_view, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_rewards_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    _user_data(context).pop(_FLOW_KEY, None)
    text, keyboard = await asyncio.to_thread(_resolve_home, update.effective_user.id)
    await query.answer()
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


async def handle_add_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    text, should_start = await asyncio.to_thread(_start_create, update.effective_user.id)
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {"action": "create_reward", "step": "name"}
    if query.message is not None:
        await query.edit_message_text(text)


async def handle_edit_reward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    raw_reward_id = query.data.removeprefix(EDIT_CALLBACK_PREFIX)
    text, should_start, keyboard = await asyncio.to_thread(
        _start_edit, update.effective_user.id, raw_reward_id
    )
    await query.answer()
    if should_start:
        _user_data(context)[_FLOW_KEY] = {
            "action": "edit_reward",
            "step": "name",
            "reward_id": raw_reward_id,
        }
    if query.message is not None:
        await query.edit_message_text(text, reply_markup=keyboard)


def _route_flow_text(
    telegram_user_id: int, flow: dict[str, Any], text: str
) -> tuple[str, InlineKeyboardMarkup | None, bool]:
    """Advances one narrowly-scoped, in-memory Add/Edit Reward flow by one
    text message. Returns (reply text, keyboard, whether the flow is now
    finished). Not a generic conversation state machine -- three fixed
    steps, name -> cost -> description, for both create and edit.
    """
    text = text.strip()
    action = flow.get("action")
    if action not in ("create_reward", "edit_reward"):
        # Unknown/stale action -- shouldn't be reachable, but never leave
        # the Adult stuck silently ignoring their input.
        return "", None, True
    is_edit = action == "edit_reward"
    # Being edited is presentation-only context for the *next* prompt
    # (showing "Current: ..."), never a business decision -- re-fetched
    # fresh each step since Reward has no delete capability to race against.
    editing_reward = _reward_for_edit_prompt(flow) if is_edit else None

    step = flow.get("step")

    if step == "name":
        if not text:
            return "Please enter a name.", None, False
        flow["name"] = text
        flow["step"] = "cost"
        prompt = (
            render_edit_prompt_cost(editing_reward)
            if editing_reward
            else render_create_prompt_cost()
        )
        return prompt, None, False

    if step == "cost":
        cost_points, error = _parse_cost(text)
        if error is not None or cost_points is None:
            return error or "Please enter a whole number of points.", None, False
        flow["cost_points"] = cost_points
        flow["step"] = "description"
        prompt = (
            render_edit_prompt_description(editing_reward)
            if editing_reward
            else render_create_prompt_description()
        )
        return prompt, None, False

    if step == "description":
        description: str | None = None if text.lower() == _SKIP_KEYWORD else text
        if is_edit:
            result_text, keyboard = _finish_edit(
                telegram_user_id, flow["reward_id"], flow["name"], flow["cost_points"], description
            )
        else:
            result_text, keyboard = _finish_create(
                telegram_user_id, flow["name"], flow["cost_points"], description
            )
        return result_text, keyboard, True

    return "", None, True


def _reward_for_edit_prompt(flow: dict[str, Any]) -> Reward | None:
    """Re-fetches the Reward being edited purely to show its *current*
    value in the next step's prompt (Issue #30: "existing values should be
    presented... so the flow does not accidentally erase fields") -- a
    read for presentation, not a business decision, so it's fine to do it
    here rather than threading it through the flow dict.
    """
    db = SessionLocal()
    try:
        try:
            reward_id = uuid.UUID(flow["reward_id"])
        except ValueError:
            return None
        return db.get(Reward, reward_id)
    finally:
        db.close()


async def handle_reward_flow_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The Add/Edit Reward free-text interaction. A text message with no
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
