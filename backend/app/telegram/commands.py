from telegram import BotCommand

from app.models import UserRole

# Single source of truth for the bot's native command menu (Issue #35) --
# both `bot.py` (default/global registration at startup) and
# `handlers/start.py` (per-chat, role-scoped registration once identity is
# resolved) import from here rather than each defining their own list.
_HOME_COMMAND = BotCommand("start", "Главная")

CHILD_COMMANDS: list[BotCommand] = [
    _HOME_COMMAND,
    BotCommand("tasks", "Доступные задачи"),
    BotCommand("mytasks", "Твои задачи"),
    BotCommand("rewards", "Доступные награды"),
    BotCommand("points", "Твои баллы"),
    BotCommand("goals", "Цели"),
]

ADULT_COMMANDS: list[BotCommand] = [
    _HOME_COMMAND,
    BotCommand("users", "Пользователи"),
    BotCommand("tasks", "Все задачи"),
    BotCommand("confirmations", "Подтверждения"),
    BotCommand("rewards", "Награды"),
    BotCommand("points", "Баллы"),
    BotCommand("goals", "Цели"),
]

# Shown to a Telegram account before it's connected to any User -- the only
# command that means anything at that point.
DEFAULT_COMMANDS: list[BotCommand] = [_HOME_COMMAND]


def commands_for_role(role: UserRole) -> list[BotCommand]:
    return ADULT_COMMANDS if role == UserRole.ADULT else CHILD_COMMANDS
