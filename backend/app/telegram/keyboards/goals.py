import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.goal_operations import GoalDetailsView
from app.models import Goal, GoalStatus
from app.telegram.keyboards.adult_points import decode_uuid, encode_uuid

LIST_CALLBACK_DATA = "goals:list"
OPEN_CALLBACK_PREFIX = "goal:open:"
TRANSFER_CALLBACK_PREFIX = "goal:transfer:"
# Bare, no payload: the pending goal/amount live in the same per-chat,
# in-memory flow state the amount prompt itself just populated (see
# handlers/goals.py's _FLOW_KEY), exactly like Adult Points' Adjust flow
# reads flow["child_id"]/flow["magnitude"] rather than round-tripping them
# through callback_data.
TRANSFER_CONFIRM_CALLBACK_DATA = "goal:transferconfirm"
# Two UUIDs (goal_id + cursor) packed via encode_uuid (Issue: Adult Points
# pagination fix) -- unpacked, this would already exceed Telegram's 64-byte
# callback_data limit, exactly like that fix's Older button did.
OLDER_CALLBACK_PREFIX = "goal:older:"


def goals_list_keyboard(goals: list[Goal]) -> InlineKeyboardMarkup:
    """One row per currently-ACTIVE Goal (Issue: Goals) -- matches
    available_tasks_keyboard/rewards_keyboard's shape: the Goal is
    represented only by its button (name + nominal cost), no verb, since
    tapping it is self-evidently "open this Goal". The callback payload
    only identifies the Goal for routing -- the Application layer
    re-verifies everything when the callback is handled.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{goal.name} · 💰 {goal.cost_points}",
                callback_data=f"{OPEN_CALLBACK_PREFIX}{goal.id}",
            )
        ]
        for goal in goals
    ]
    return InlineKeyboardMarkup(rows)


def goal_details_keyboard(view: GoalDetailsView) -> InlineKeyboardMarkup:
    """`Перевести баллы` only while the Goal is still ACTIVE (Issue: Goals)
    -- a COMPLETED Goal offers no transfer action at all, matching the
    Child Points screen's "no button when there's nothing to do" shape.
    `Ранее` only when another history page exists.
    """
    rows = []
    if view.goal.status == GoalStatus.ACTIVE:
        rows.append(
            [
                InlineKeyboardButton(
                    "Перевести баллы", callback_data=f"{TRANSFER_CALLBACK_PREFIX}{view.goal.id}"
                )
            ]
        )
    if view.next_cursor is not None:
        payload = f"{encode_uuid(view.goal.id)}:{encode_uuid(view.next_cursor)}"
        rows.append(
            [InlineKeyboardButton("Ранее", callback_data=f"{OLDER_CALLBACK_PREFIX}{payload}")]
        )
    rows.append([InlineKeyboardButton("← Назад", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def decode_older_payload(raw: str) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Inverse of goal_details_keyboard's `Ранее` payload -- returns
    (goal_id, cursor), either of which is None if malformed (a stale or
    crafted callback gracefully falls back rather than erroring, matching
    every other pagination callback in this project).
    """
    raw_goal_token, _, raw_cursor_token = raw.partition(":")
    return decode_uuid(raw_goal_token), decode_uuid(raw_cursor_token)


def transfer_confirmation_keyboard(goal_id: uuid.UUID) -> InlineKeyboardMarkup:
    """`Перевести` (act, reads the pending amount from flow state) /
    `Назад` (abort, back to the Goal Details screen the transfer started
    from). Deliberately no payload on the confirm button: see
    TRANSFER_CONFIRM_CALLBACK_DATA above.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Перевести", callback_data=TRANSFER_CONFIRM_CALLBACK_DATA
                )
            ],
            [InlineKeyboardButton("Назад", callback_data=f"{OPEN_CALLBACK_PREFIX}{goal_id}")],
        ]
    )


def back_to_goal_keyboard(goal_id: uuid.UUID) -> InlineKeyboardMarkup:
    """A minimal way back to a specific Goal's own details -- used by the
    amount prompt's abandon path and by stale/invalid-state rejections
    that still know which Goal was involved.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Назад", callback_data=f"{OPEN_CALLBACK_PREFIX}{goal_id}")]]
    )


def back_to_goals_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Goal/action can't be shown at all (not
    found, or input was invalid) -- the Child must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Назад", callback_data=LIST_CALLBACK_DATA)]]
    )
