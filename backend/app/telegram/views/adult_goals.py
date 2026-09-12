from app.models import Goal

ALL_GOALS_HEADING = "Все цели"
NO_GOALS_TEXT = "Целей пока нет."


def render_goals_list(goals: list[Goal]) -> str:
    """Issue: Goals -- just the heading, matching render_tasks_list/
    render_rewards_list: every Goal (active or completed) is fully
    represented by its own button (adult_goals.goals_list_keyboard).
    """
    if not goals:
        return f"{ALL_GOALS_HEADING}\n\n{NO_GOALS_TEXT}"
    return ALL_GOALS_HEADING


def render_create_prompt_name() -> str:
    return "Как называется цель?"


def render_create_prompt_cost() -> str:
    return "Сколько баллов нужно накопить?"


def render_edit_menu(goal: Goal) -> str:
    return (
        f"Редактирование цели\n\nТекущее название:\n{goal.name}\n\n"
        f"Текущая стоимость:\n{goal.cost_points}"
    )


def render_edit_prompt_name(goal: Goal) -> str:
    return f"Текущее название:\n{goal.name}\n\nОтправьте новое название."


def render_edit_prompt_cost(goal: Goal) -> str:
    return f"Текущая стоимость:\n{goal.cost_points}\n\nОтправьте новую стоимость в баллах."


def render_goal_created(goal: Goal) -> str:
    return f"«{goal.name}» создана."


def render_goal_updated(goal: Goal) -> str:
    return f"«{goal.name}» обновлена."
