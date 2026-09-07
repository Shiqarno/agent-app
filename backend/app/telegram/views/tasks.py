from app.models import Task, TaskExecution, TaskExecutionStatus

NO_TASKS_AVAILABLE_TEXT = "No tasks available right now."
NO_TASKS_IN_PROGRESS_TEXT = "You have no tasks in progress."


def render_available_tasks(tasks: list[Task]) -> str:
    """Issue #24 section 1: name, reward, nothing else -- no description, no
    status, no Adult/creator information.
    """
    if not tasks:
        return NO_TASKS_AVAILABLE_TEXT
    return "\n\n".join(f"{task.title} · {task.reward_points} pts" for task in tasks)


def render_my_tasks(items: list[tuple[TaskExecution, Task]]) -> str:
    """Issue #24 section 3: IN_PROGRESS shows just name/reward (the Done
    button carries the CTA); AWAITING_CONFIRMATION additionally shows a
    waiting line and gets no CTA at all.
    """
    if not items:
        return NO_TASKS_IN_PROGRESS_TEXT

    blocks = []
    for execution, task in items:
        block = f"{task.title} · {execution.reward_points} pts"
        if execution.status == TaskExecutionStatus.AWAITING_CONFIRMATION:
            block += "\nWaiting for confirmation"
        blocks.append(block)
    return "\n\n".join(blocks)


def render_task_taken(task: Task) -> str:
    return f"{task.title} started."


def render_execution_marked_ready(task: Task) -> str:
    return f"{task.title} marked as done and sent for confirmation."
