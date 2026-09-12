from datetime import datetime

from app.points_operations import PointsView

NO_TRANSACTIONS_TEXT = "Пока нет операций."

# Genitive-case short month names for `_format_date` below -- Russian date
# formatting has no locale-independent equivalent of `strftime("%b")` that
# doesn't depend on the process's system locale being installed/set, so this
# stays a small local table rather than an actual i18n dependency.
_SHORT_MONTHS_GENITIVE = [
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
]


def _format_amount(amount: int) -> str:
    return f"+💰 {amount}" if amount >= 0 else f"-💰 {-amount}"


def _format_date(created_at: datetime, now: datetime) -> str:
    delta_days = (now.date() - created_at.date()).days
    if delta_days == 0:
        return "Сегодня"
    if delta_days == 1:
        return "Вчера"
    return f"{created_at.day} {_SHORT_MONTHS_GENITIVE[created_at.month - 1]}"


def render_points(view: PointsView, now: datetime) -> str:
    """Issue #27 "Points screen": balance first, then history newest-first
    with a human-readable source description and a relative date -- never
    the raw `PointTransactionReason` or a database timestamp.
    """
    header = f"Баллы\n\nБаланс\n💰 {view.balance}"
    if not view.transactions:
        return f"{header}\n\n{NO_TRANSACTIONS_TEXT}"

    blocks = [
        f"{_format_amount(item.amount)}\n{item.description}\n{_format_date(item.created_at, now)}"
        for item in view.transactions
    ]
    return header + "\n\n" + "\n\n".join(blocks)
