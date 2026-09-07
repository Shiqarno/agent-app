from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, TaskExecutionStatus

TASKS_CALLBACK_PREFIX = "task:take:"
EXECUTION_DONE_CALLBACK_PREFIX = "execution:done:"


def available_tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    """One `Take` row per Task. The callback payload only identifies the
    Task (Issue #24 section 15) -- it is never treated as authorization, the
    Application layer re-verifies everything when the callback is handled.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"Take · {task.title}", callback_data=f"{TASKS_CALLBACK_PREFIX}{task.id}"
            )
        ]
        for task in tasks
    ]
    return InlineKeyboardMarkup(rows)


def my_tasks_keyboard(items: list[tuple[TaskExecution, Task]]) -> InlineKeyboardMarkup:
    """A `Done` row only for IN_PROGRESS executions -- AWAITING_CONFIRMATION
    items get no CTA at all (Issue #24 section 3).
    """
    rows = [
        [
            InlineKeyboardButton(
                f"Done · {task.title}",
                callback_data=f"{EXECUTION_DONE_CALLBACK_PREFIX}{execution.id}",
            )
        ]
        for execution, task in items
        if execution.status == TaskExecutionStatus.IN_PROGRESS
    ]
    return InlineKeyboardMarkup(rows)
