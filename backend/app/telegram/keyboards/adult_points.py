import base64
import binascii
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


def encode_uuid(value: uuid.UUID) -> str:
    """Packs a UUID's raw 16 bytes as unpadded urlsafe-base64 (22 chars)
    instead of its 36-char hyphenated hex form. This is a lossless,
    reversible re-encoding -- never a truncation -- so it carries no
    collision risk; it exists purely so a callback carrying more than one
    UUID (e.g. the `Older` button's child_id + cursor here, or Adult Tasks'
    Assign-to-Child's task_id + child_id) can still fit inside Telegram's
    64-byte `callback_data` limit (Issue: `Button_data_invalid`). Public --
    reused by other Telegram keyboards modules with the same problem rather
    than each reimplementing it.
    """
    return base64.urlsafe_b64encode(value.bytes).rstrip(b"=").decode("ascii")


def decode_uuid(raw: str) -> uuid.UUID | None:
    """Inverse of `encode_uuid`. Returns None for anything malformed
    (stale/crafted callback data) so callers can fall back gracefully
    instead of raising.
    """
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding)
    except (ValueError, binascii.Error):
        return None
    if len(decoded) != 16:
        return None
    return uuid.UUID(bytes=decoded)


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
                f"{child.name} — 💰 {balance}", callback_data=f"{OPEN_CALLBACK_PREFIX}{child.id}"
            )
        ]
        for child, balance in items
    ]
    rows.append([InlineKeyboardButton("← Домой", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def child_points_keyboard(child_id: uuid.UUID, view: PointsView) -> InlineKeyboardMarkup:
    """`Older` only when another page exists, plus `Adjust points` and
    `← Back` (Issue #31 "Child Points details").
    """
    rows = []
    if view.next_cursor is not None:
        # Both ids are packed via `encode_uuid` (not the 36-char hyphenated
        # form): unpacked, `child_id` + `:` + `next_cursor` alone would
        # already exceed Telegram's 64-byte callback_data limit.
        payload = f"{encode_uuid(child_id)}:{encode_uuid(view.next_cursor)}"
        rows.append(
            [InlineKeyboardButton("Ранее", callback_data=f"{OLDER_CALLBACK_PREFIX}{payload}")]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "Изменить баллы", callback_data=f"{ADJUST_CALLBACK_PREFIX}{child_id}"
            )
        ]
    )
    rows.append([InlineKeyboardButton("← Назад", callback_data=LIST_CALLBACK_DATA)])
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
                    "+ Начислить баллы", callback_data=f"{ADD_CALLBACK_PREFIX}{child_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "- Списать баллы", callback_data=f"{REMOVE_CALLBACK_PREFIX}{child_id}"
                )
            ],
            [InlineKeyboardButton("← Назад", callback_data=f"{OPEN_CALLBACK_PREFIX}{child_id}")],
        ]
    )


def back_to_children_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Child/action can't be shown at all (not
    found, or input was invalid) -- the Adult must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Назад", callback_data=LIST_CALLBACK_DATA)]]
    )
