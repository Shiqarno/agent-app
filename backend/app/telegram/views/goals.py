from datetime import datetime

from app.goal_operations import GoalDetailsView
from app.models import Goal, GoalStatus
from app.telegram.views.points import _format_amount, _format_date

GOALS_HEADING = "Цели"
NO_GOALS_TEXT = "Пока нет доступных целей."
NO_CONTRIBUTIONS_TEXT = "Пока нет переводов."
_GOAL_ACHIEVED_TEXT = "✓ Цель достигнута"


def render_goals_list(goals: list[Goal]) -> str:
    """Issue: Goals -- just the heading, matching render_available_tasks/
    render_rewards: every active Goal is fully represented by its own
    button (goals_list_keyboard), so nothing is duplicated as text above it.
    """
    if not goals:
        return f"{GOALS_HEADING}\n\n{NO_GOALS_TEXT}"
    return GOALS_HEADING


def _contribution_history(view: GoalDetailsView, now: datetime) -> str:
    if not view.contributions:
        return f"История переводов\n\n{NO_CONTRIBUTIONS_TEXT}"
    blocks = [
        f"{_format_amount(item.amount)}\n{item.child_name}\n{_format_date(item.created_at, now)}"
        for item in view.contributions
    ]
    return "История переводов\n\n" + "\n\n".join(blocks)


def render_goal_details(view: GoalDetailsView, now: datetime) -> str:
    """Issue: Goals -- name, nominal cost, accumulated points, and the
    contribution history together (Also show the transfer history), same
    "everything needed in one screen" shape as render_child_points. A
    COMPLETED Goal keeps its full history (Issue: "Completed Goals retain
    their history") and additionally shows the achieved marker -- never an
    internal `GoalStatus` name.
    """
    goal = view.goal
    header = (
        f"{goal.name}\n\n"
        f"Стоимость: 💰 {goal.cost_points}\n"
        f"Накоплено: 💰 {goal.accumulated_points}"
    )
    if goal.status == GoalStatus.COMPLETED:
        header += f"\n\n{_GOAL_ACHIEVED_TEXT}"
    return f"{header}\n\n{_contribution_history(view, now)}"


def render_transfer_amount_prompt(available_balance: int, remaining: int) -> str:
    return (
        f"Сколько баллов перевести?\n\n"
        f"Доступно: 💰 {available_balance}\n"
        f"До цели осталось: 💰 {remaining}"
    )


def render_transfer_confirmation(goal: Goal, amount: int, balance_after: int) -> str:
    return (
        f"Перевести 💰 {amount} баллов в цель\n«{goal.name}»?\n\n"
        f"После перевода у тебя останется:\n💰 {balance_after}"
    )


def render_transfer_success(goal: Goal, amount: int) -> str:
    """`goal` is the already-updated Goal returned by contribute_to_goal --
    `accumulated_points`/`status` reflect the transfer that just happened.
    """
    header = f"В цель переведено 💰 {amount} баллов."
    progress = f"Накоплено: 💰 {goal.accumulated_points} / {goal.cost_points}"
    if goal.status == GoalStatus.COMPLETED:
        return f"{header}\n\n{goal.name}\n{progress}\n\n{_GOAL_ACHIEVED_TEXT}"
    return f"{header}\n\n{progress}"
