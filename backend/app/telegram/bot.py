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
from app.telegram.handlers.adult_tasks import (
    handle_activate_task,
    handle_add_task,
    handle_deactivate_task,
    handle_edit_menu,
    handle_edit_name,
    handle_edit_reward,
    handle_home,
    handle_list_tasks,
    handle_open_task,
    handle_task_flow_text,
    handle_tasks_command,
)
from app.telegram.handlers.confirmations import (
    handle_confirm_execution,
    handle_confirmations_command,
    handle_return_execution,
    handle_view_all_confirmations,
)
from app.telegram.handlers.points import handle_older_points, handle_points_command
from app.telegram.handlers.rewards import handle_get_reward, handle_rewards_command
from app.telegram.handlers.start import handle_start
from app.telegram.handlers.tasks import handle_mark_ready, handle_my_tasks_command, handle_take_task
from app.telegram.keyboards.adult_tasks import (
    ACTIVATE_CALLBACK_PREFIX,
    ADD_CALLBACK_DATA,
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
from app.telegram.keyboards.points import OLDER_CALLBACK_PREFIX
from app.telegram.keyboards.rewards import GET_CALLBACK_PREFIX as REWARD_GET_CALLBACK_PREFIX
from app.telegram.keyboards.tasks import EXECUTION_DONE_CALLBACK_PREFIX, TASKS_CALLBACK_PREFIX

logger = logging.getLogger(__name__)

# PTB's Application is generic over its bot/context/data types; this process
# never needs anything beyond the library's own defaults, so the type
# parameters are left open rather than pinned to internal library types.
BotApplication = Application[Any, Any, Any, Any, Any, Any]


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A single bad update must never take the process down (Issue #23) --
    the library already isolates exceptions raised inside a handler to that
    one update, but without an error handler they'd only go to stderr; this
    logs them properly so a real failure isn't silently lost.
    """
    logger.error("Unhandled error while processing update %r", update, exc_info=context.error)


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

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("tasks", handle_tasks_command))
    application.add_handler(CommandHandler("mytasks", handle_my_tasks_command))
    application.add_handler(
        CallbackQueryHandler(handle_take_task, pattern=f"^{TASKS_CALLBACK_PREFIX}")
    )
    application.add_handler(
        CallbackQueryHandler(handle_mark_ready, pattern=f"^{EXECUTION_DONE_CALLBACK_PREFIX}")
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
    application.add_handler(CommandHandler("rewards", handle_rewards_command))
    application.add_handler(
        CallbackQueryHandler(handle_get_reward, pattern=f"^{REWARD_GET_CALLBACK_PREFIX}")
    )
    application.add_handler(CommandHandler("points", handle_points_command))
    application.add_handler(
        CallbackQueryHandler(handle_older_points, pattern=f"^{OLDER_CALLBACK_PREFIX}")
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_flow_text))
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
