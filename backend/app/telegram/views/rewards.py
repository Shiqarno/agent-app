from app.models import Reward, RewardRedemption

AVAILABLE_REWARDS_HEADING = "Доступные награды"
NO_REWARDS_TEXT_PREFIX = "Нет доступных наград."


def render_rewards(rewards: list[Reward], available_balance: int) -> str:
    """Issue #26 "Rewards list" / Issue #36: heading and balance, then text
    only for unaffordable Rewards -- those get no button at all (nothing
    to tap), so a text line is the only way they stay visible. An
    affordable Reward is fully represented by its own button (no `Get`
    verb -- Issue #39: tapping it *requests* the Reward, not redeems it),
    so nothing is duplicated as separate text for it.

    `available_balance` (Issue #39: ledger balance minus this Child's own
    active pending reward requests) is what's shown and what decides
    affordability here -- not the raw ledger balance -- so the banner
    never contradicts which buttons are actually shown below it.
    """
    header = f"{AVAILABLE_REWARDS_HEADING}\nУ тебя {available_balance} баллов"
    if not rewards:
        return f"{header}\n\n{NO_REWARDS_TEXT_PREFIX}"

    unaffordable_blocks = [
        f"{reward.name} · 💰 {reward.cost_points}\nНедостаточно баллов"
        for reward in rewards
        if available_balance < reward.cost_points
    ]
    if not unaffordable_blocks:
        return header
    return header + "\n\n" + "\n\n".join(unaffordable_blocks)


def render_reward_requested(reward: Reward, available_balance: int) -> str:
    """Issue #39: replaces the old immediate `render_redemption_success` --
    tapping a Reward now only sends a request to an Adult; the Reward is
    not yet handed out, and no points are actually deducted from the
    ledger until that Adult confirms it (see
    app/telegram/views/confirmations.py for that side).
    """
    return (
        f"Награда запрошена!\n\n{reward.name} · {reward.cost_points} баллов\n"
        f"Запрос отправлен взрослому на подтверждение — "
        f"зарезервировано {reward.cost_points} баллов.\n"
        f"Доступно баллов: {available_balance}."
    )


def render_reward_confirmed_notification(redemption: RewardRedemption, reward: Reward) -> str:
    """Child-facing outbound notification sent once an Adult confirms this
    request (Issue: Telegram notifications) -- cost comes from the
    redemption's own frozen snapshot, never the Reward's current cost,
    matching render_reward_confirmation_detail's existing convention.
    """
    return (
        f"Награда подтверждена:\n\n{reward.name}\n\nПотрачено 💰 {redemption.cost_points} баллов."
    )
