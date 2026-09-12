import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.goal_operations import GoalDetailsView
from app.models import Goal, GoalStatus
from app.telegram.keyboards.adult_points import decode_uuid, encode_uuid

OPEN_CALLBACK_PREFIX = "adultgoal:open:"
ADD_CALLBACK_DATA = "adultgoal:add"
LIST_CALLBACK_DATA = "adultgoal:list"
HOME_CALLBACK_DATA = "adultgoal:home"
EDIT_CALLBACK_PREFIX = "adultgoal:edit:"
EDIT_NAME_CALLBACK_PREFIX = "adultgoal:editname:"
EDIT_COST_CALLBACK_PREFIX = "adultgoal:editcost:"
# Two UUIDs (goal_id + cursor) packed via encode_uuid (Issue: Adult Points
# pagination fix), reused here for the Adult Goal Details history -- a
# separate prefix/handler from the Child's goal:older: (Issue: Goals),
# matching the existing Adult Points/Child Points precedent of one
# pagination route per role-scoped screen rather than a shared one.
OLDER_CALLBACK_PREFIX = "adultgoal:older:"


def _goal_button_label(goal: Goal) -> str:
    """A COMPLETED Goal's button gets a `✓` marker (Issue: Goals) -- no
    internal `GoalStatus` name is ever shown -- matching the existing
    `❌` marker Adult Tasks already uses for an inactive Task's button.
    """
    if goal.status == GoalStatus.COMPLETED:
        return f"✓ {goal.name} · 💰 {goal.cost_points}"
    return f"{goal.name} · 💰 {goal.cost_points}"


def goals_list_keyboard(goals: list[Goal]) -> InlineKeyboardMarkup:
    """One row per Goal -- active and completed both, for management
    (Issue: Goals) -- plus `+ Add goal` and `← Home`, matching
    tasks_list_keyboard's shape.
    """
    rows = [
        [
            InlineKeyboardButton(
                _goal_button_label(goal), callback_data=f"{OPEN_CALLBACK_PREFIX}{goal.id}"
            )
        ]
        for goal in goals
    ]
    rows.append([InlineKeyboardButton("+ Добавить цель", callback_data=ADD_CALLBACK_DATA)])
    rows.append([InlineKeyboardButton("← Домой", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def goal_details_keyboard(view: GoalDetailsView) -> InlineKeyboardMarkup:
    """`Изменить` only while the Goal is still ACTIVE (Issue: Goals) -- a
    COMPLETED Goal cannot be edited at all, matching update_goal's own
    refusal. `Ранее` only when another history page exists.
    """
    rows = []
    if view.goal.status == GoalStatus.ACTIVE:
        rows.append(
            [
                InlineKeyboardButton(
                    "Изменить", callback_data=f"{EDIT_CALLBACK_PREFIX}{view.goal.id}"
                )
            ]
        )
    if view.next_cursor is not None:
        payload = f"{encode_uuid(view.goal.id)}:{encode_uuid(view.next_cursor)}"
        rows.append(
            [InlineKeyboardButton("Ранее", callback_data=f"{OLDER_CALLBACK_PREFIX}{payload}")]
        )
    rows.append([InlineKeyboardButton("← Цели", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def decode_older_payload(raw: str) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Inverse of goal_details_keyboard's `Ранее` payload -- returns
    (goal_id, cursor), either of which is None if malformed.
    """
    raw_goal_token, _, raw_cursor_token = raw.partition(":")
    return decode_uuid(raw_goal_token), decode_uuid(raw_cursor_token)


def edit_menu_keyboard(goal: Goal) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Изменить название", callback_data=f"{EDIT_NAME_CALLBACK_PREFIX}{goal.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Изменить стоимость", callback_data=f"{EDIT_COST_CALLBACK_PREFIX}{goal.id}"
                )
            ],
            [InlineKeyboardButton("← Цели", callback_data=LIST_CALLBACK_DATA)],
        ]
    )


def back_to_goals_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Goal/action can't be shown at all (not
    found, or input was invalid) -- the Adult must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Цели", callback_data=LIST_CALLBACK_DATA)]]
    )
