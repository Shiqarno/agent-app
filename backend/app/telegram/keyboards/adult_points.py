import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import User
from app.points_operations import PointsView

OPEN_CALLBACK_PREFIX = "adultpoints:open:"
LIST_CALLBACK_DATA = "adultpoints:list"
HOME_CALLBACK_DATA = "adultpoints:home"
OLDER_CALLBACK_PREFIX = "adultpoints:older:"
ADJUST_CALLBACK_PREFIX = "adultpoints:adjust:"
ADD_CALLBACK_PREFIX = "adultpoints:add:"
REMOVE_CALLBACK_PREFIX = "adultpoints:remove:"


def points_children_keyboard(items: list[tuple[User, int]]) -> InlineKeyboardMarkup:
    """One row per Child (Issue #31 "Points list") -- deliberately no
    `+ Add` row (unlike Users/Rewards): this list is navigation-only, never
    a place to create a User. The callback payload only identifies the
    Child for routing -- the Application layer re-verifies role on every
    call.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{child.name} — {balance} pts", callback_data=f"{OPEN_CALLBACK_PREFIX}{child.id}"
            )
        ]
        for child, balance in items
    ]
    rows.append([InlineKeyboardButton("← Home", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def child_points_keyboard(child_id: uuid.UUID, view: PointsView) -> InlineKeyboardMarkup:
    """`Older` only when another page exists, plus `Adjust points` and
    `← Back` (Issue #31 "Child Points details").
    """
    rows = []
    if view.next_cursor is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    "Older",
                    callback_data=f"{OLDER_CALLBACK_PREFIX}{child_id}:{view.next_cursor}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("Adjust points", callback_data=f"{ADJUST_CALLBACK_PREFIX}{child_id}")]
    )
    rows.append([InlineKeyboardButton("← Back", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def adjust_menu_keyboard(child_id: uuid.UUID) -> InlineKeyboardMarkup:
    """`+ Add points` / `- Remove points` / `← Back` (Issue #31 "Adjust
    Points flow") -- the Adult never types a signed amount; the button
    itself determines the direction, and the Telegram adapter negates the
    magnitude for removal before calling `adjust_points`.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "+ Add points", callback_data=f"{ADD_CALLBACK_PREFIX}{child_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "- Remove points", callback_data=f"{REMOVE_CALLBACK_PREFIX}{child_id}"
                )
            ],
            [InlineKeyboardButton("← Back", callback_data=f"{OPEN_CALLBACK_PREFIX}{child_id}")],
        ]
    )


def back_to_children_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Child/action can't be shown at all (not
    found, or input was invalid) -- the Adult must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Back", callback_data=LIST_CALLBACK_DATA)]]
    )
