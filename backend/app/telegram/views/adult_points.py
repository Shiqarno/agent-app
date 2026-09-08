from datetime import datetime

from app.models import User
from app.points_operations import PointsView
from app.telegram.views.points import NO_TRANSACTIONS_TEXT, _format_amount, _format_date

NO_CHILDREN_TEXT = "No children yet."


def render_children_points_list(items: list[tuple[User, int]]) -> str:
    """Issue #31 "Points list": Child name and current balance only -- no
    Adult rows, no history.
    """
    if not items:
        return f"💰 Points\n\n{NO_CHILDREN_TEXT}"
    blocks = [f"{child.name} — {balance} pts" for child, balance in items]
    return "💰 Points\n\n" + "\n".join(blocks)


def render_child_points(child: User, view: PointsView, now: datetime) -> str:
    """Issue #31 "Child Points details": same balance+history rendering as
    the Child's own self-service Points screen, headed with the Child's
    name so the Adult always knows whose ledger they're looking at.
    """
    header = f"{child.name}\n\nBalance\n{view.balance} pts"
    if not view.transactions:
        return f"{header}\n\n{NO_TRANSACTIONS_TEXT}"
    blocks = [
        f"{_format_amount(item.amount)}\n{item.description}\n{_format_date(item.created_at, now)}"
        for item in view.transactions
    ]
    return header + "\n\n" + "\n\n".join(blocks)


def render_adjust_menu(child: User, balance: int) -> str:
    return f"Adjust points for {child.name}.\n\nCurrent balance: {balance} pts"


def render_amount_prompt(direction: str, child: User) -> str:
    verb = "add" if direction == "add" else "remove"
    return f"How many points would you like to {verb} for {child.name}?"


def render_description_prompt(direction: str) -> str:
    verb = "adding" if direction == "add" else "removing"
    return f"Why are you {verb} these points?"


def render_adjustment_success(child: User, amount: int, new_balance: int) -> str:
    sign = "+" if amount >= 0 else ""
    return f"{sign}{amount} pts for {child.name}.\n\n{child.name} now has {new_balance} pts."


def render_insufficient_balance(child: User, magnitude: int, balance: int) -> str:
    return f"Current balance: {balance} pts.\n\nYou cannot remove {magnitude} points."
