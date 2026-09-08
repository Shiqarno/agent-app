import logging
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.telegram.commands import DEFAULT_COMMANDS
from app.telegram.handlers import adult_points, adult_rewards, adult_tasks, adult_users
from app.telegram.handlers.adult_points import (
    handle_adjust_menu,
    handle_list_children,
    handle_older_child_points,
    handle_open_child_points,
    handle_points_home,
    handle_start_add,
    handle_start_remove,
)
from app.telegram.handlers.adult_points import (
    handle_points_command as handle_points_command_dispatch,
)
from app.telegram.handlers.adult_rewards import (
    handle_add_reward,
    handle_open_reward,
)
from app.telegram.handlers.adult_rewards import (
    handle_edit_reward as handle_edit_reward_entry,
)
from app.telegram.handlers.adult_rewards import (
    handle_list_rewards as handle_list_rewards_catalog,
)
from app.telegram.handlers.adult_rewards import (
    handle_rewards_command as handle_rewards_command_dispatch,
)
from app.telegram.handlers.adult_rewards import (
    handle_rewards_home as handle_rewards_home_catalog,
)
from app.telegram.handlers.adult_tasks import (
    handle_activate_task,
    handle_add_task,
    handle_assign_menu,
    handle_assign_to_child,
    handle_deactivate_task,
    handle_edit_menu,
    handle_edit_name,
    handle_edit_reward,
    handle_home,
    handle_list_tasks,
    handle_open_task,
    handle_tasks_command,
)
from app.telegram.handlers.adult_users import (
    handle_add_child,
    handle_get_activation_link,
    handle_list_users,
    handle_open_user,
    handle_users_command,
    handle_users_home,
)
from app.telegram.handlers.confirmations import (
    handle_confirm_execution,
    handle_confirmations_command,
    handle_open_confirmation,
    handle_return_execution,
    handle_view_all_confirmations,
)
from app.telegram.handlers.points import handle_older_points
from app.telegram.handlers.rewards import handle_get_reward
from app.telegram.handlers.start import handle_start
from app.telegram.handlers.tasks import (
    handle_mark_ready,
    handle_my_tasks_command,
    handle_start_execution,
    handle_take_task,
)
from app.telegram.keyboards.adult_points import (
    ADD_CALLBACK_PREFIX as ADULT_POINTS_ADD_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_points import (
    ADJUST_CALLBACK_PREFIX as ADULT_POINTS_ADJUST_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_points import (
    HOME_CALLBACK_DATA as ADULT_POINTS_HOME_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_points import (
    LIST_CALLBACK_DATA as ADULT_POINTS_LIST_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_points import (
    OLDER_CALLBACK_PREFIX as ADULT_POINTS_OLDER_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_points import (
    OPEN_CALLBACK_PREFIX as ADULT_POINTS_OPEN_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_points import (
    REMOVE_CALLBACK_PREFIX as ADULT_POINTS_REMOVE_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_rewards import (
    ADD_CALLBACK_DATA as ADD_REWARD_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_rewards import (
    EDIT_CALLBACK_PREFIX as REWARD_EDIT_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_rewards import (
    HOME_CALLBACK_DATA as REWARDS_HOME_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_rewards import (
    LIST_CALLBACK_DATA as REWARDS_LIST_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_rewards import (
    OPEN_CALLBACK_PREFIX as ADULT_REWARD_OPEN_CALLBACK_PREFIX,
)
from app.telegram.keyboards.adult_tasks import (
    ACTIVATE_CALLBACK_PREFIX,
    ADD_CALLBACK_DATA,
    ASSIGN_CALLBACK_PREFIX,
    ASSIGN_TO_CALLBACK_PREFIX,
    DEACTIVATE_CALLBACK_PREFIX,
    EDIT_CALLBACK_PREFIX,
    EDIT_NAME_CALLBACK_PREFIX,
    EDIT_REWARD_CALLBACK_PREFIX,
    HOME_CALLBACK_DATA,
    LIST_CALLBACK_DATA,
)
from app.telegram.keyboards.adult_tasks import (
    OPEN_CALLBACK_PREFIX as ADULT_TASK_OPEN_CALLBACK_PREFIX,
)
from app.telegram.keyboards.confirmations import (
    CONFIRM_CALLBACK_PREFIX,
    RETURN_CALLBACK_PREFIX,
    VIEW_ALL_CALLBACK_DATA,
)
from app.telegram.keyboards.confirmations import (
    OPEN_CALLBACK_PREFIX as CONFIRMATION_OPEN_CALLBACK_PREFIX,
)
from app.telegram.keyboards.points import OLDER_CALLBACK_PREFIX
from app.telegram.keyboards.rewards import GET_CALLBACK_PREFIX as REWARD_GET_CALLBACK_PREFIX
from app.telegram.keyboards.tasks import (
    EXECUTION_DONE_CALLBACK_PREFIX,
    EXECUTION_START_CALLBACK_PREFIX,
    TASKS_CALLBACK_PREFIX,
)
from app.telegram.keyboards.users import (
    ADD_CHILD_CALLBACK_DATA,
    GET_LINK_CALLBACK_PREFIX,
)
from app.telegram.keyboards.users import (
    HOME_CALLBACK_DATA as USERS_HOME_CALLBACK_DATA,
)
from app.telegram.keyboards.users import (
    LIST_CALLBACK_DATA as USERS_LIST_CALLBACK_DATA,
)
from app.telegram.keyboards.users import (
    OPEN_CALLBACK_PREFIX as ADULT_USER_OPEN_CALLBACK_PREFIX,
)

logger = logging.getLogger(__name__)

# PTB's Application is generic over its bot/context/data types; this process
# never needs anything beyond the library's own defaults, so the type
# parameters are left open rather than pinned to internal library types.
BotApplication = Application[Any, Any, Any, Any, Any, Any]


async def _handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatches a free-text message to whichever short-lived input flow
    (Adult Tasks Create/Edit, Adult Users Add Child, Adult Rewards
    Add/Edit, Adult Points Adjust) is currently open for this Adult, based
    on which `context.user_data` flow key is present. PTB only ever runs
    the first matching handler for a given update within a handler group,
    so a single generic-text MessageHandler must own this routing rather
    than registering one per feature.
    """
    data = context.user_data or {}
    if adult_tasks._FLOW_KEY in data:
        await adult_tasks.handle_task_flow_text(update, context)
    elif adult_users._FLOW_KEY in data:
        await adult_users.handle_user_flow_text(update, context)
    elif adult_rewards._FLOW_KEY in data:
        await adult_rewards.handle_reward_flow_text(update, context)
    elif adult_points._FLOW_KEY in data:
        await adult_points.handle_points_flow_text(update, context)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A single bad update must never take the process down (Issue #23) --
    the library already isolates exceptions raised inside a handler to that
    one update, but without an error handler they'd only go to stderr; this
    logs them properly so a real failure isn't silently lost.
    """
    logger.error("Unhandled error while processing update %r", update, exc_info=context.error)


async def _set_default_commands(application: BotApplication) -> None:
    """Sets the bot's global command menu (Issue #35) -- shown to any chat
    that hasn't had a role-specific menu set yet via `/start`
    (handlers/start.py), i.e. a not-yet-connected Telegram account. Runs
    once at process startup (PTB's `post_init` hook), not at
    `build_application()` time, so constructing an Application for tests
    still makes no network call.
    """
    await application.bot.set_my_commands(DEFAULT_COMMANDS)


def build_application() -> BotApplication:
    """Constructs the bot Application and registers every handler. Pure
    object construction -- no network call happens here (that starts with
    `run_polling()`), so this can be exercised in tests without a real
    Telegram token or connectivity.
    """
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured -- set it in the environment "
            "before starting the Telegram bot process."
        )

    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_set_default_commands)
        .build()
    )
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("tasks", handle_tasks_command))
    application.add_handler(CommandHandler("mytasks", handle_my_tasks_command))
    application.add_handler(
        CallbackQueryHandler(handle_take_task, pattern=f"^{TASKS_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_mark_ready, pattern=f"^{EXECUTION_DONE_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_start_execution, pattern=f"^{EXECUTION_START_CALLBACK_PREFIX}")
    )
    application.add_handler(CommandHandler("confirmations", handle_confirmations_command))
    application.add_handler(
        CallbackQueryHandler(handle_confirm_execution, pattern=f"^{CONFIRM_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_return_execution, pattern=f"^{RETURN_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_view_all_confirmations, pattern=f"^{VIEW_ALL_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_open_confirmation, pattern=f"^{CONFIRMATION_OPEN_CALLBACK_PREFIX}"
        )
    )
    application.add_handler(CommandHandler("rewards", handle_rewards_command_dispatch))
    application.add_handler(
        CallbackQueryHandler(handle_get_reward, pattern=f"^{REWARD_GET_CALLBACK_PREFIX}")
    )
    application.add_handler(CommandHandler("points", handle_points_command_dispatch))
    application.add_handler(
        CallbackQueryHandler(handle_older_points, pattern=f"^{OLDER_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_open_child_points, pattern=f"^{ADULT_POINTS_OPEN_CALLBACK_PREFIX}"
        )
    )
    application.add_handler(
        CallbackQueryHandler(handle_list_children, pattern=f"^{ADULT_POINTS_LIST_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_points_home, pattern=f"^{ADULT_POINTS_HOME_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_older_child_points, pattern=f"^{ADULT_POINTS_OLDER_CALLBACK_PREFIX}"
        )
    )
    application.add_handler(
        CallbackQueryHandler(handle_adjust_menu, pattern=f"^{ADULT_POINTS_ADJUST_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_start_add, pattern=f"^{ADULT_POINTS_ADD_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_start_remove, pattern=f"^{ADULT_POINTS_REMOVE_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_open_task, pattern=f"^{ADULT_TASK_OPEN_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_list_tasks, pattern=f"^{LIST_CALLBACK_DATA}$")
    )
    application.add_handler(CallbackQueryHandler(handle_home, pattern=f"^{HOME_CALLBACK_DATA}$"))
    application.add_handler(CallbackQueryHandler(handle_add_task, pattern=f"^{ADD_CALLBACK_DATA}$"))
    application.add_handler(
        CallbackQueryHandler(handle_edit_menu, pattern=f"^{EDIT_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_name, pattern=f"^{EDIT_NAME_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_reward, pattern=f"^{EDIT_REWARD_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_activate_task, pattern=f"^{ACTIVATE_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_deactivate_task, pattern=f"^{DEACTIVATE_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_assign_to_child, pattern=f"^{ASSIGN_TO_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_assign_menu, pattern=f"^{ASSIGN_CALLBACK_PREFIX}")
    )
    application.add_handler(CommandHandler("users", handle_users_command))
    application.add_handler(
        CallbackQueryHandler(handle_open_user, pattern=f"^{ADULT_USER_OPEN_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_list_users, pattern=f"^{USERS_LIST_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_users_home, pattern=f"^{USERS_HOME_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_add_child, pattern=f"^{ADD_CHILD_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_get_activation_link, pattern=f"^{GET_LINK_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_open_reward, pattern=f"^{ADULT_REWARD_OPEN_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_list_rewards_catalog, pattern=f"^{REWARDS_LIST_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_rewards_home_catalog, pattern=f"^{REWARDS_HOME_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_add_reward, pattern=f"^{ADD_REWARD_CALLBACK_DATA}$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_reward_entry, pattern=f"^{REWARD_EDIT_CALLBACK_PREFIX}")
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_text_input))
    application.add_error_handler(_on_error)
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    application = build_application()
    # Long polling, a single consumer, no webhook (Issue #23). run_polling()
    # itself installs SIGINT/SIGTERM handlers and shuts down gracefully.
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
