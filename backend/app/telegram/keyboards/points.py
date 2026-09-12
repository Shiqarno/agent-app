from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.points_operations import PointsView

OLDER_CALLBACK_PREFIX = "points:older:"


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
