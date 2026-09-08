from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Reward

OPEN_CALLBACK_PREFIX = "adultreward:open:"
ADD_CALLBACK_DATA = "adultreward:add"
LIST_CALLBACK_DATA = "adultreward:list"
HOME_CALLBACK_DATA = "adultreward:home"
EDIT_CALLBACK_PREFIX = "adultreward:edit:"


def rewards_list_keyboard(rewards: list[Reward]) -> InlineKeyboardMarkup:
    """One row per Reward, plus `+ Add Reward` and `← Home` (Issue #30
    "Rewards list"). Each button shows name and cost (Issue #36) so the
    Adult doesn't need to open every Reward to see them. The callback
    payload only identifies the Reward for routing -- the Application
    layer re-verifies role/existence on every call.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{reward.name} · 💰 {reward.cost_points}",
                callback_data=f"{OPEN_CALLBACK_PREFIX}{reward.id}",
            )
        ]
        for reward in rewards
    ]
    rows.append([InlineKeyboardButton("+ Add Reward", callback_data=ADD_CALLBACK_DATA)])
    rows.append([InlineKeyboardButton("← Home", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def reward_details_keyboard(reward: Reward) -> InlineKeyboardMarkup:
    """Edit and Back only (Issue #30 "Reward details") -- deliberately no
    Delete, no activate/deactivate; Reward has no such concept.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Edit", callback_data=f"{EDIT_CALLBACK_PREFIX}{reward.id}")],
            [InlineKeyboardButton("← Back", callback_data=LIST_CALLBACK_DATA)],
        ]
    )


def back_to_rewards_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Reward/action can't be shown at all (not
    found, or input was invalid) -- the Adult must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Back", callback_data=LIST_CALLBACK_DATA)]]
    )
