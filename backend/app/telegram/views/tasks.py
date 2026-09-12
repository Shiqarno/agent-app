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
