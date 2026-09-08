from app.models import Reward

AVAILABLE_REWARDS_HEADING = "Доступные награды"
NO_REWARDS_TEXT_PREFIX = "Нет доступных наград."


def render_rewards(rewards: list[Reward], balance: int) -> str:
    """Issue #26 "Rewards list" / Issue #36: heading and balance, then text
    only for unaffordable Rewards -- those get no button at all (nothing
    to tap), so a text line is the only way they stay visible. An
    affordable Reward is fully represented by its own Get-less button
    (rewards_keyboard, name + cost already there), so nothing is
    duplicated as separate text for it.
    """
    header = f"{AVAILABLE_REWARDS_HEADING}\nYou have {balance} points"
    if not rewards:
        return f"{header}\n\n{NO_REWARDS_TEXT_PREFIX}"

    unaffordable_blocks = [
        f"{reward.name} · {reward.cost_points} pts\nNot enough points"
        for reward in rewards
        if balance < reward.cost_points
    ]
    if not unaffordable_blocks:
        return header
    return header + "\n\n" + "\n\n".join(unaffordable_blocks)


def render_redemption_success(reward: Reward, remaining_balance: int) -> str:
    return (
        f"Reward received!\n\n{reward.name} · {reward.cost_points} points\n"
        f"Remaining: {remaining_balance} points"
    )
