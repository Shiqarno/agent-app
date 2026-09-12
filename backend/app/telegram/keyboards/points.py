from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.points_operations import PointsView

OLDER_CALLBACK_PREFIX = "points:older:"
# Child-side "reopen this screen" callback (Issue: Telegram notifications) --
# /points previously had no callback route back into itself, only its slash
# command. A notification's button needs one to reopen the existing flow.
LIST_CALLBACK_DATA = "points:list"


def points_keyboard(view: PointsView) -> InlineKeyboardMarkup:
    """An `Older` button only when another page exists (Issue #27
    "Pagination"). The callback payload carries only the cursor id for
    routing -- never a trusted balance/ownership claim; the Application
    layer resolves and re-scopes it to the current User on every call.
    """
    if view.next_cursor is None:
        return InlineKeyboardMarkup([])
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Ранее", callback_data=f"{OLDER_CALLBACK_PREFIX}{view.next_cursor}"
                )
            ]
        ]
    )


def points_notification_keyboard() -> InlineKeyboardMarkup:
    """Attached to the Child "Task confirmed" notification (Issue:
    Telegram notifications) -- opens the existing /points flow via
    LIST_CALLBACK_DATA (handled by handle_points_list).
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Мои баллы", callback_data=LIST_CALLBACK_DATA)]]
    )
