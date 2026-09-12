"""Proactive Telegram notifications for task/reward events (Issue: Telegram
notifications).

Deliberately a thin, Telegram-specific adapter, not a general event bus:
each `notify_*` function is called directly by the Telegram handler that
just completed the corresponding Application-layer operation, strictly
*after* that operation's own commit has already succeeded (every caller
site places the call immediately after the operation returns normally --
an operation that raises never reaches its notify call). A delivery
failure here is caught and logged, never re-raised, so it can never affect
the business operation that already committed; this module reuses that
already-committed operation's own domain objects and connects to a
Telegram account only when one is on file for the recipient, exactly as
required by Issue #23's existing "no connection -> presentation-only
message" precedent -- here, "no connection -> skip delivery".

Every button reuses an existing callback route (either an Adult navigation
callback that already existed, or one of the four new Child "reopen this
screen" callbacks added in keyboards/tasks.py, keyboards/points.py, and
keyboards/rewards.py) -- there is no notification-specific screen.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Bot, InlineKeyboardMarkup
from telegram.error import TelegramError

from app.config import settings
from app.models import (
    Reward,
    RewardRedemption,
    Task,
    TaskExecution,
    TelegramIdentity,
    User,
    UserRole,
)
from app.task_operations import get_available_tasks
from app.telegram.keyboards.confirmations import confirmations_notification_keyboard
from app.telegram.keyboards.points import points_notification_keyboard
from app.telegram.keyboards.rewards import rewards_notification_keyboard
from app.telegram.keyboards.tasks import (
    my_tasks_notification_keyboard,
    tasks_notification_keyboard,
)
from app.telegram.views.confirmations import (
    render_reward_awaiting_confirmation_notification,
    render_task_awaiting_confirmation_notification,
)
from app.telegram.views.rewards import render_reward_confirmed_notification
from app.telegram.views.tasks import (
    render_task_assigned_notification,
    render_task_available_notification,
    render_task_confirmed_notification,
)
from app.telegram_identity import get_telegram_user_id

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        # Matches build_application()'s own guard (bot.py) -- by the time any
        # handler is actually running, the bot process could not have started
        # without a configured token.
        if not settings.telegram_bot_token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not configured -- cannot send Telegram notifications."
            )
        _bot = Bot(token=settings.telegram_bot_token)
    return _bot


async def _send_async(telegram_user_id: int, text: str, keyboard: InlineKeyboardMarkup) -> None:
    try:
        await _get_bot().send_message(chat_id=telegram_user_id, text=text, reply_markup=keyboard)
    except TelegramError:
        logger.warning(
            "Failed to deliver Telegram notification to user %s", telegram_user_id, exc_info=True
        )


def _send(telegram_user_id: int, text: str, keyboard: InlineKeyboardMarkup) -> None:
    """Synchronous bridge: every notify_* call below happens from code
    already running inside `asyncio.to_thread` (see each handler's
    `_finish_*`/`_confirm*`/`_mark_ready`/`_request` function) -- a worker
    thread with no event loop of its own, exactly what `asyncio.run`
    requires. Catches broadly, not just `TelegramError`: delivery must
    never break the already-committed business operation, regardless of
    what goes wrong (a misconfigured token, a network stack error other
    than the ones python-telegram-bot wraps, etc.).
    """
    try:
        asyncio.run(_send_async(telegram_user_id, text, keyboard))
    except Exception:
        logger.exception(
            "Unexpected error sending Telegram notification to user %s", telegram_user_id
        )


def _connected_adults(db: Session) -> list[tuple[User, int]]:
    """Every Adult who currently has a Telegram account connected (Issue
    #39/#25: no Adult<->Child ownership -- any Adult may confirm any
    pending item, so every connected Adult is "eligible" for these two
    notifications, matching confirm_execution/confirm_reward_redemption's
    own authorization model exactly).
    """
    stmt = (
        select(User, TelegramIdentity.telegram_user_id)
        .join(TelegramIdentity, TelegramIdentity.user_id == User.id)
        .where(User.role == UserRole.ADULT)
    )
    return [(user, telegram_user_id) for user, telegram_user_id in db.execute(stmt).all()]


def _connected_children(db: Session) -> list[tuple[User, int]]:
    stmt = (
        select(User, TelegramIdentity.telegram_user_id)
        .join(TelegramIdentity, TelegramIdentity.user_id == User.id)
        .where(User.role == UserRole.CHILD)
    )
    return [(user, telegram_user_id) for user, telegram_user_id in db.execute(stmt).all()]


def notify_task_awaiting_confirmation(db: Session, task: Task, child: User) -> None:
    """Adult(s): a Child's execution just reached AWAITING_CONFIRMATION."""
    text = render_task_awaiting_confirmation_notification(task, child)
    keyboard = confirmations_notification_keyboard()
    for _adult, telegram_user_id in _connected_adults(db):
        _send(telegram_user_id, text, keyboard)


def notify_reward_awaiting_confirmation(
    db: Session, redemption: RewardRedemption, reward: Reward, child: User
) -> None:
    """Adult(s): a Child's reward request just reached PENDING_CONFIRMATION."""
    text = render_reward_awaiting_confirmation_notification(redemption, reward, child)
    keyboard = confirmations_notification_keyboard()
    for _adult, telegram_user_id in _connected_adults(db):
        _send(telegram_user_id, text, keyboard)


def notify_task_available(db: Session, task: Task) -> None:
    """Every connected Child for whom this Task is now available to
    self-claim -- reuses `get_available_tasks` (the exact same read
    `/tasks` itself uses) per Child, rather than re-deriving the
    availability rule, so a Child who happens to already hold an open
    execution of this Task (only possible via a reactivation, since a
    freshly-created Task has no executions at all) is correctly skipped.
    """
    text = render_task_available_notification(task)
    keyboard = tasks_notification_keyboard()
    for child, telegram_user_id in _connected_children(db):
        available = get_available_tasks(db, child)
        if any(candidate.id == task.id for candidate in available):
            _send(telegram_user_id, text, keyboard)


def notify_task_assigned(db: Session, task: Task, child: User, execution: TaskExecution) -> None:
    telegram_user_id = get_telegram_user_id(db, child.id)
    if telegram_user_id is None:
        return
    text = render_task_assigned_notification(task, execution)
    _send(telegram_user_id, text, my_tasks_notification_keyboard())


def notify_task_confirmed(db: Session, task: Task, child: User, execution: TaskExecution) -> None:
    telegram_user_id = get_telegram_user_id(db, child.id)
    if telegram_user_id is None:
        return
    text = render_task_confirmed_notification(task, execution)
    _send(telegram_user_id, text, points_notification_keyboard())


def notify_reward_confirmed(
    db: Session, redemption: RewardRedemption, reward: Reward, child: User
) -> None:
    telegram_user_id = get_telegram_user_id(db, child.id)
    if telegram_user_id is None:
        return
    text = render_reward_confirmed_notification(redemption, reward)
    _send(telegram_user_id, text, rewards_notification_keyboard())
