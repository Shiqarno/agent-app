import logging
from typing import Any

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from app.config import settings
from app.telegram.handlers.start import handle_start

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
