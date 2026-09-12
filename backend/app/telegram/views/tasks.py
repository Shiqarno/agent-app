from app.models import Task, TaskExecution, TaskExecutionStatus

AVAILABLE_TASKS_HEADING = "Доступные задачи"
MY_TASKS_HEADING = "Твои задачи"
NO_TASKS_AVAILABLE_TEXT = "Нет доступных задач."
NO_TASKS_IN_PROGRESS_TEXT = "У тебя нет активных задач."


def render_available_tasks(tasks: list[Task]) -> str:
    """Issue #24 section 1 / Issue #36: just the heading -- name and reward
    live only on each Task's Take button (available_tasks_keyboard), never
    duplicated as a separate text block above it.
    """
    if not tasks:
        return f"{AVAILABLE_TASKS_HEADING}\n\n{NO_TASKS_AVAILABLE_TEXT}"
    return AVAILABLE_TASKS_HEADING


def render_my_tasks(items: list[tuple[TaskExecution, Task]]) -> str:
    """Issue #24 section 3 / Issue #36: heading, then text only for
    AWAITING_CONFIRMATION items -- those get no button at all (no action
    is possible), so a text line is the only way they stay visible.
    ASSIGNED/IN_PROGRESS items are fully represented by their own Start/
    Done button (my_tasks_keyboard, name + reward already there), so
    nothing is duplicated as separate text for them.
    """
    if not items:
        return f"{MY_TASKS_HEADING}\n\n{NO_TASKS_IN_PROGRESS_TEXT}"

    waiting_blocks = [
        f"{task.title} · 💰 {execution.reward_points}\nОжидает подтверждения"
        for execution, task in items
        if execution.status == TaskExecutionStatus.AWAITING_CONFIRMATION
    ]
    if not waiting_blocks:
        return MY_TASKS_HEADING
    return f"{MY_TASKS_HEADING}\n\n" + "\n\n".join(waiting_blocks)


def render_task_taken(task: Task) -> str:
    return f"«{task.title}» начата."


def render_execution_marked_ready(task: Task) -> str:
    return f"«{task.title}» отмечена как выполненная и отправлена на подтверждение."


def render_task_available_notification(task: Task) -> str:
    """Child-facing outbound notification (Issue: Telegram notifications):
    sent when a Task becomes newly available for self-claim (created
    active, or reactivated) -- the reward shown is the Task's own current
    value, since no TaskExecution (and therefore no snapshot) exists yet.
    """
    return f"Появилась новая доступная задача:\n\n{task.title}\n💰 {task.reward_points}"


def render_task_assigned_notification(task: Task, execution: TaskExecution) -> str:
    """Child-facing outbound notification for direct assignment (Issue:
    Telegram notifications) -- distinct from adult_tasks.render_task_assigned,
    which is the Adult's own confirmation text after tapping a Child in the
    Assign flow. Uses the new execution's own reward snapshot, matching
    every other reward amount shown to a Child about their own execution.
    """
    return f"Тебе назначена новая задача:\n\n{task.title}\n💰 {execution.reward_points}"


def render_task_confirmed_notification(task: Task, execution: TaskExecution) -> str:
    """Child-facing outbound notification sent once an Adult confirms this
    execution (Issue: Telegram notifications) -- the reward shown is the
    execution's own immutable snapshot, never the Task's current reward,
    matching every other confirmed-amount display in the app.
    """
    return (
        f"Задача подтверждена:\n\n{task.title}\n\nТы получил 💰 {execution.reward_points} баллов."
    )
