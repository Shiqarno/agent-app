from datetime import datetime

from app.points_operations import PointsView

NO_TRANSACTIONS_TEXT = "No transactions yet."


def _format_amount(amount: int) -> str:
    return f"+{amount} pts" if amount >= 0 else f"{amount} pts"


def _format_date(created_at: datetime, now: datetime) -> str:
    delta_days = (now.date() - created_at.date()).days
    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Yesterday"
    return created_at.strftime("%b %-d")


def render_points(view: PointsView, now: datetime) -> str:
    """Issue #27 "Points screen": balance first, then history newest-first
    with a human-readable source description and a relative date -- never
    the raw `PointTransactionReason` or a database timestamp.
    """
    header = f"Points\n\nBalance\n{view.balance} pts"
    if not view.transactions:
        return f"{header}\n\n{NO_TRANSACTIONS_TEXT}"

    blocks = [
        f"{_format_amount(item.amount)}\n{item.description}\n{_format_date(item.created_at, now)}"
        for item in view.transactions
    ]
    return header + "\n\n" + "\n\n".join(blocks)
