from datetime import datetime

from app.models import User
from app.points_operations import PointsView
from app.telegram.views.points import NO_TRANSACTIONS_TEXT, _format_amount, _format_date

NO_CHILDREN_TEXT = "Детей пока нет."


def render_children_points_list(items: list[tuple[User, int]]) -> str:
    """Issue #31 "Points list": Child name and current balance only -- no
    Adult rows, no history.
    """
    if not items:
        return f"💰 Баллы\n\n{NO_CHILDREN_TEXT}"
    blocks = [f"{child.name} — 💰 {balance}" for child, balance in items]
    return "💰 Баллы\n\n" + "\n".join(blocks)


def render_child_points(child: User, view: PointsView, now: datetime) -> str:
    """Issue #31 "Child Points details": same balance+history rendering as
    the Child's own self-service Points screen, headed with the Child's
    name so the Adult always knows whose ledger they're looking at.
    """
    header = f"{child.name}\n\nБаланс\n💰 {view.balance}"
    if not view.transactions:
        return f"{header}\n\n{NO_TRANSACTIONS_TEXT}"
    blocks = [
        f"{_format_amount(item.amount)}\n{item.description}\n{_format_date(item.created_at, now)}"
        for item in view.transactions
    ]
    return header + "\n\n" + "\n\n".join(blocks)


def render_adjust_menu(child: User, balance: int) -> str:
    return f"Изменение баллов для {child.name}.\n\nТекущий баланс: 💰 {balance}"


def render_amount_prompt(direction: str, child: User) -> str:
    if direction == "add":
        return f"Сколько баллов начислить {child.name}?"
    return f"Сколько баллов списать у {child.name}?"


def render_description_prompt(direction: str) -> str:
    if direction == "add":
        return "За что начисляются баллы?"
    return "За что списываются баллы?"


def render_adjustment_success(child: User, amount: int, new_balance: int) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}💰 {abs(amount)} для {child.name}.\n\nТеперь у {child.name} 💰 {new_balance}."


def render_insufficient_balance(child: User, magnitude: int, balance: int) -> str:
    return (
        f"Недостаточно доступных баллов.\n\n"
        f"Доступно: 💰 {balance}. Нельзя списать: 💰 {magnitude}."
    )
