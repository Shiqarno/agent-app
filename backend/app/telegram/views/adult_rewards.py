from app.models import Reward

NO_REWARDS_TEXT = "Наград пока нет."


def render_rewards_list(rewards: list[Reward]) -> str:
    """Issue #30 section "Rewards list" / Issue #36: just the heading --
    every Reward always has its own button (rewards_list_keyboard), which
    already shows name and cost, so nothing is duplicated as separate
    text above it.
    """
    if not rewards:
        return f"🎁 Награды\n\n{NO_REWARDS_TEXT}"
    return "🎁 Награды"


def render_reward_details(reward: Reward) -> str:
    """Issue #30 "Reward details": name, cost, description -- no Delete, no
    activation/deactivation (Reward has no is_active concept at all).
    """
    description = reward.description if reward.description else "(нет)"
    return f"🎁 {reward.name}\n\nСтоимость: {reward.cost_points} баллов\n\nОписание:\n{description}"


def render_create_prompt_name() -> str:
    return "Как называется награда?"


def render_create_prompt_cost() -> str:
    return "Сколько баллов она стоит?"


def render_create_prompt_description() -> str:
    return "Отправьте описание или напишите «пропустить», чтобы оставить пустым."


def render_edit_prompt_name(reward: Reward) -> str:
    return f"Текущее название:\n{reward.name}\n\nОтправьте новое название."


def render_edit_prompt_cost(reward: Reward) -> str:
    return f"Текущая стоимость:\n{reward.cost_points} баллов\n\nОтправьте новую стоимость в баллах."


def render_edit_prompt_description(reward: Reward) -> str:
    current = reward.description if reward.description else "(нет)"
    return (
        f"Текущее описание:\n{current}\n\n"
        "Отправьте новое описание или напишите «пропустить», чтобы оставить без изменений."
    )


def render_reward_created(reward: Reward) -> str:
    return f"«{reward.name}» создана."


def render_reward_updated(reward: Reward) -> str:
    return f"«{reward.name}» обновлена."
