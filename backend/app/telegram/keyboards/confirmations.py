from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, User

CONFIRM_CALLBACK_PREFIX = "confirmation:confirm:"
RETURN_CALLBACK_PREFIX = "confirmation:return:"
VIEW_ALL_CALLBACK_DATA = "confirmation:list"


def confirmation_queue_keyboard(
    items: list[tuple[TaskExecution, Task, User]],
) -> InlineKeyboardMarkup:
    """One row per execution, each with both actions (Issue #25 section 3) --
    the callback payload only identifies the execution for routing, never
    authorization; the Application layer re-verifies everything.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"Confirm · {task.title}", callback_data=f"{CONFIRM_CALLBACK_PREFIX}{execution.id}"
            ),
            InlineKeyboardButton(
                f"Return · {task.title}", callback_data=f"{RETURN_CALLBACK_PREFIX}{execution.id}"
            ),
        ]
        for execution, task, _ in items
    ]
    return InlineKeyboardMarkup(rows)


def confirmation_summary_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("View all", callback_data=VIEW_ALL_CALLBACK_DATA)]]
    )
