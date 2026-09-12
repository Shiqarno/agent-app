from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, TaskExecutionStatus

TASKS_CALLBACK_PREFIX = "task:take:"
EXECUTION_DONE_CALLBACK_PREFIX = "execution:done:"
EXECUTION_START_CALLBACK_PREFIX = "execution:start:"
# Child-side "reopen this screen" callbacks (Issue: Telegram notifications):
# unlike the Adult screens, Child /tasks and /mytasks previously had no
# callback route back into themselves -- they were reachable only via their
# slash command. A notification's button needs one to reopen the existing
# flow rather than a new notification-specific screen.
LIST_CALLBACK_DATA = "tasks:list"
MY_TASKS_CALLBACK_DATA = "mytasks:list"


def available_tasks_keyboard(tasks: list[Task]) -> InlineKeyboardMarkup:
    """One row per Task, its reward included directly on the button
    (Issue #35) so the Child can see it without opening Task Details --
    the Task is represented only by its button (Issue #36), so no `Take`
    verb or separate name text; tapping it is self-evidently the action.
    The reward leads the label (Issue #39: `<reward>💰 · <name>`) rather
    than trailing it, so the Child scans amounts first -- deliberately
    different from every other Task/Reward button in the app, which keep
    name-first (`Name · 💰 amount`); this is scoped to Child `/tasks` only.
    The callback payload only identifies the Task (Issue #24 section 15)
    -- it is never treated as authorization, the Application layer
    re-verifies everything when the callback is handled.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{task.reward_points}💰 · {task.title}",
                callback_data=f"{TASKS_CALLBACK_PREFIX}{task.id}",
            )
        ]
        for task in tasks
    ]
    return InlineKeyboardMarkup(rows)


def my_tasks_keyboard(items: list[tuple[TaskExecution, Task]]) -> InlineKeyboardMarkup:
    """A row for each ASSIGNED execution (Start) and each IN_PROGRESS one
    (Done) -- AWAITING_CONFIRMATION items get no CTA at all. No `Start`/
    `Done` verb on the button (Issue #36): the execution is represented
    only by its button, so just name + reward -- the execution's own
    snapshot (Issue #35), never the Task's current reward, which can have
    since changed.
    """
    rows = []
    for execution, task in items:
        if execution.status == TaskExecutionStatus.ASSIGNED:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{task.title} · 💰 {execution.reward_points}",
                        callback_data=f"{EXECUTION_START_CALLBACK_PREFIX}{execution.id}",
                    )
                ]
            )
        elif execution.status == TaskExecutionStatus.IN_PROGRESS:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{task.title} · 💰 {execution.reward_points}",
                        callback_data=f"{EXECUTION_DONE_CALLBACK_PREFIX}{execution.id}",
                    )
                ]
            )
    return InlineKeyboardMarkup(rows)


def tasks_notification_keyboard() -> InlineKeyboardMarkup:
    """Attached to the Child "Task available" notification (Issue:
    Telegram notifications) -- opens the existing /tasks flow via
    LIST_CALLBACK_DATA (handled by handle_tasks_list), never a new screen.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Задачи", callback_data=LIST_CALLBACK_DATA)]]
    )


def my_tasks_notification_keyboard() -> InlineKeyboardMarkup:
    """Attached to the Child "Task assigned" notification (Issue: Telegram
    notifications) -- opens the existing /mytasks flow via
    MY_TASKS_CALLBACK_DATA (handled by handle_my_tasks_list).
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Мои задачи", callback_data=MY_TASKS_CALLBACK_DATA)]]
    )
