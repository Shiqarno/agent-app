from app.models import Reward

AVAILABLE_REWARDS_HEADING = "Доступные награды"
NO_REWARDS_TEXT_PREFIX = "Нет доступных наград."


def render_rewards(rewards: list[Reward], balance: int) -> str:
    """Issue #26 "Rewards list" / Issue #35: heading, balance, name, cost,
    and an affordability line -- no description, no technical status.
    """
    header = f"{AVAILABLE_REWARDS_HEADING}\nYou have {balance} points"
    if not rewards:
        return f"{header}\n\n{NO_REWARDS_TEXT_PREFIX}"

    blocks = []
    for reward in rewards:
        block = f"{reward.name} · {reward.cost_points} pts"
        if balance < reward.cost_points:
            block += "\nNot enough points"
        blocks.append(block)
    return header + "\n\n" + "\n\n".join(blocks)


def render_redemption_success(reward: Reward, remaining_balance: int) -> str:
    return (
        f"Reward received!\n\n{reward.name} · {reward.cost_points} points\n"
        f"Remaining: {remaining_balance} points"
    )
