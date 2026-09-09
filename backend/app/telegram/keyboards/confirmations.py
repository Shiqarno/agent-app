from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import RewardRedemption, TaskExecution
from app.telegram.views.confirmations import ConfirmationItem, TaskConfirmationItem

CONFIRM_CALLBACK_PREFIX = "confirmation:confirm:"
RETURN_CALLBACK_PREFIX = "confirmation:return:"
VIEW_ALL_CALLBACK_DATA = "confirmation:list"
OPEN_CALLBACK_PREFIX = "confirmation:open:"

# Reward requests (Issue #39) reuse the same list/detail screens as Task
# confirmations, but route through their own callback prefixes -- kept
# fully distinct from the ones above so the existing Task-confirmation
# callbacks/handlers never need to change shape.
OPEN_REWARD_CALLBACK_PREFIX = "confirmation:openreward:"
CONFIRM_REWARD_CALLBACK_PREFIX = "confirmation:confirmreward:"
RETURN_REWARD_CALLBACK_PREFIX = "confirmation:returnreward:"


def confirmation_list_keyboard(items: list[ConfirmationItem]) -> InlineKeyboardMarkup:
    """One row per item, Task/Reward name + Child name (Issue #36 step 1 /
    Issue #39) -- the Child name disambiguates when multiple Children have
    an item of the same Task/Reward, which a title-only button could not.
    Confirm and Return live one tap further in, on the selected item's own
    detail screen, not here. The callback payload only identifies the item
    for routing, never authorization; the Application layer re-verifies
    everything.
    """
    rows = []
    for item in items:
        if isinstance(item, TaskConfirmationItem):
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{item.task.title} · {item.child.name}",
                        callback_data=f"{OPEN_CALLBACK_PREFIX}{item.execution.id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{item.reward.name} · {item.child.name}",
                        callback_data=f"{OPEN_REWARD_CALLBACK_PREFIX}{item.redemption.id}",
                    )
                ]
            )
    return InlineKeyboardMarkup(rows)


def confirmation_detail_keyboard(execution: TaskExecution) -> InlineKeyboardMarkup:
    """Confirm/Return for exactly the selected execution (Issue #36 step 2)
    -- no title needed on these buttons, since the detail screen above them
    already names the Task. `← Back` reuses the existing list callback
    (Issue #25's `VIEW_ALL_CALLBACK_DATA`) rather than a new one.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Confirm", callback_data=f"{CONFIRM_CALLBACK_PREFIX}{execution.id}"
                ),
                InlineKeyboardButton(
                    "Return", callback_data=f"{RETURN_CALLBACK_PREFIX}{execution.id}"
                ),
            ],
            [InlineKeyboardButton("← Back", callback_data=VIEW_ALL_CALLBACK_DATA)],
        ]
    )


def reward_confirmation_detail_keyboard(redemption: RewardRedemption) -> InlineKeyboardMarkup:
    """The Reward request analogue of confirmation_detail_keyboard above
    (Issue #39): `Confirm` approves the request (actual redemption),
    `Return` rejects it (frozen points released, no redemption).
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Confirm", callback_data=f"{CONFIRM_REWARD_CALLBACK_PREFIX}{redemption.id}"
                ),
                InlineKeyboardButton(
                    "Return", callback_data=f"{RETURN_REWARD_CALLBACK_PREFIX}{redemption.id}"
                ),
            ],
            [InlineKeyboardButton("← Back", callback_data=VIEW_ALL_CALLBACK_DATA)],
        ]
    )
