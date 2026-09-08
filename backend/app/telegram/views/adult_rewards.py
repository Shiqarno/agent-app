from app.models import Reward

NO_REWARDS_TEXT = "No rewards yet."


def render_reward_list_item(reward: Reward) -> str:
    return f"{reward.name} — {reward.cost_points} pts"


def render_rewards_list(rewards: list[Reward]) -> str:
    """Issue #30 section "Rewards list": name and cost only -- no
    description, no redemption/history data.
    """
    if not rewards:
        return f"🎁 Rewards\n\n{NO_REWARDS_TEXT}"
    blocks = [render_reward_list_item(reward) for reward in rewards]
    return "🎁 Rewards\n\n" + "\n".join(blocks)


def render_reward_details(reward: Reward) -> str:
    """Issue #30 "Reward details": name, cost, description -- no Delete, no
    activation/deactivation (Reward has no is_active concept at all).
    """
    description = reward.description if reward.description else "(none)"
    return f"🎁 {reward.name}\n\nCost: {reward.cost_points} points\n\nDescription:\n{description}"


def render_create_prompt_name() -> str:
    return "What's the reward called?"


def render_create_prompt_cost() -> str:
    return "How many points does it cost?"


def render_create_prompt_description() -> str:
    return 'Send a description, or send "skip" to leave it blank.'


def render_edit_prompt_name(reward: Reward) -> str:
    return f"Current name:\n{reward.name}\n\nSend the new name."


def render_edit_prompt_cost(reward: Reward) -> str:
    return f"Current cost:\n{reward.cost_points} points\n\nSend the new cost, in points."


def render_edit_prompt_description(reward: Reward) -> str:
    current = reward.description if reward.description else "(none)"
    return (
        f"Current description:\n{current}\n\n"
        'Send the new description, or send "skip" to keep it unchanged.'
    )


def render_reward_created(reward: Reward) -> str:
    return f"{reward.name} was created."


def render_reward_updated(reward: Reward) -> str:
    return f"{reward.name} was updated."
