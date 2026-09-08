from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Reward

GET_CALLBACK_PREFIX = "reward:get:"


def rewards_keyboard(rewards: list[Reward], balance: int) -> InlineKeyboardMarkup:
    """One row per currently-affordable Reward (Issue #26) -- an
    unaffordable Reward gets no button at all, matching the "Not enough
    points" text in the view. Each button includes the Reward's current
    cost (Issue #35); no `Get` verb (Issue #36) -- the Reward is
    represented only by its button, and tapping it is self-evidently the
    action. The callback payload only identifies the Reward for routing,
    never cost/balance/authorization; the Application layer re-verifies
    everything using the current Reward and ledger state.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{reward.name} · {reward.cost_points} pts",
                callback_data=f"{GET_CALLBACK_PREFIX}{reward.id}",
            )
        ]
        for reward in rewards
        if balance >= reward.cost_points
    ]
    return InlineKeyboardMarkup(rows)
