from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, TaskExecutionStatus

TASKS_CALLBACK_PREFIX = "task:take:"
EXECUTION_DONE_CALLBACK_PREFIX = "execution:done:"
EXECUTION_START_CALLBACK_PREFIX = "execution:start:"


def available_tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    """One `Take` row per Task, its reward included directly on the button
    (Issue #35) so the Child can see it without opening Task Details. The
    callback payload only identifies the Task (Issue #24 section 15) -- it
    is never treated as authorization, the Application layer re-verifies
    everything when the callback is handled.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"Take · {task.title} · {task.reward_points} pts",
                callback_data=f"{TASKS_CALLBACK_PREFIX}{task.id}",
            )
        ]
        for task in tasks
    ]
    return InlineKeyboardMarkup(rows)


def my_tasks_keyboard(items: list[tuple[TaskExecution, Task]]) -> InlineKeyboardMarkup:
    """A `Start` row for ASSIGNED executions (Issue #32) and a `Done` row
    for IN_PROGRESS ones (Issue #24 section 3) -- AWAITING_CONFIRMATION
    items get no CTA at all. Each button includes the execution's own
    reward snapshot (Issue #35) -- never the Task's current reward, which
    can have since changed.
    """
    rows = []
    for execution, task in items:
        if execution.status == TaskExecutionStatus.ASSIGNED:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"Start · {task.title} · {execution.reward_points} pts",
                        callback_data=f"{EXECUTION_START_CALLBACK_PREFIX}{execution.id}",
                    )
                ]
            )
        elif execution.status == TaskExecutionStatus.IN_PROGRESS:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"Done · {task.title} · {execution.reward_points} pts",
                        callback_data=f"{EXECUTION_DONE_CALLBACK_PREFIX}{execution.id}",
                    )
                ]
            )
    return InlineKeyboardMarkup(rows)
