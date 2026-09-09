from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Reward

REQUEST_CALLBACK_PREFIX = "reward:request:"


def rewards_keyboard(rewards: list[Reward], available_balance: int) -> InlineKeyboardMarkup:
    """One row per currently-affordable Reward (Issue #26) -- an
    unaffordable Reward gets no button at all, matching the "Not enough
    points" text in the view. Each button includes the Reward's current
    cost (Issue #35); no `Get` verb (Issue #36) -- the Reward is
    represented only by its button, and tapping it is self-evidently the
    action (Issue #39: that action is now a *request*, not an immediate
    redemption). The callback payload only identifies the Reward for
    routing, never cost/balance/authorization; the Application layer
    re-verifies everything using the current Reward and ledger state.

    Affordability is judged against `available_balance` (Issue #39:
    ledger balance minus this Child's own active pending reward requests),
    not the raw ledger balance -- a Reward the Child could only afford by
    ignoring a request they already have pending must not show a button.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{reward.name} · 💰 {reward.cost_points}",
                callback_data=f"{REQUEST_CALLBACK_PREFIX}{reward.id}",
            )
        ]
        for reward in rewards
        if available_balance >= reward.cost_points
    ]
    return InlineKeyboardMarkup(rows)
