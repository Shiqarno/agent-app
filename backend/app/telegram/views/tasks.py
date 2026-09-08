from app.models import Task, TaskExecution, TaskExecutionStatus

AVAILABLE_TASKS_HEADING = "Доступные задачи"
MY_TASKS_HEADING = "Твои задачи"
NO_TASKS_AVAILABLE_TEXT = "Нет доступных задач."
NO_TASKS_IN_PROGRESS_TEXT = "У тебя нет активных задач."


def render_available_tasks(tasks: list[Task]) -> str:
    """Issue #24 section 1 / Issue #35: heading, then name and reward per
    Task -- no description, no status, no Adult/creator information.
    """
    if not tasks:
        return f"{AVAILABLE_TASKS_HEADING}\n\n{NO_TASKS_AVAILABLE_TEXT}"
    blocks = "\n\n".join(f"{task.title} · {task.reward_points} pts" for task in tasks)
    return f"{AVAILABLE_TASKS_HEADING}\n\n{blocks}"


def render_my_tasks(items: list[tuple[TaskExecution, Task]]) -> str:
    """Issue #24 section 3 / Issue #35: heading, then IN_PROGRESS shows just
    name/reward (the Done button carries the CTA); AWAITING_CONFIRMATION
    additionally shows a waiting line and gets no CTA at all.
    """
    if not items:
        return f"{MY_TASKS_HEADING}\n\n{NO_TASKS_IN_PROGRESS_TEXT}"

    blocks = []
    for execution, task in items:
        block = f"{task.title} · {execution.reward_points} pts"
        if execution.status == TaskExecutionStatus.ASSIGNED:
            block += "\nAssigned to you"
        elif execution.status == TaskExecutionStatus.AWAITING_CONFIRMATION:
            block += "\nWaiting for confirmation"
        blocks.append(block)
    return f"{MY_TASKS_HEADING}\n\n" + "\n\n".join(blocks)


def render_task_taken(task: Task) -> str:
    return f"{task.title} started."


def render_execution_marked_ready(task: Task) -> str:
    return f"{task.title} marked as done and sent for confirmation."
