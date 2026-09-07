from app.models import Task, TaskExecution, User

NO_CONFIRMATIONS_TEXT = "No tasks waiting for confirmation."


def render_confirmation_queue(items: list[tuple[TaskExecution, Task, User]]) -> str:
    """Issue #25 section 3/21: Task title, Child name, reward snapshot,
    nothing else -- no description, no history, no technical status names.
    """
    if not items:
        return NO_CONFIRMATIONS_TEXT
    return "\n\n".join(
        f"{task.title} · {child.name} · {execution.reward_points} pts"
        for execution, task, child in items
    )


def render_confirmation_summary(items: list[tuple[TaskExecution, Task, User]]) -> str:
    """The Adult Home action block (Issue #25 section 1) -- a short preview,
    not the full queue.
    """
    count = len(items)
    noun = "task" if count == 1 else "tasks"
    lines = [
        f"{task.title} · {child.name} · {execution.reward_points} pts"
        for execution, task, child in items
    ]
    header = f"Task Confirmation\n\n{count} {noun} waiting for confirmation"
    return f"{header}\n\n" + "\n".join(lines)


def render_execution_confirmed(task: Task, child: User, execution: TaskExecution) -> str:
    return f"{task.title} confirmed -- {child.name} earned {execution.reward_points} pts."


def render_execution_returned(task: Task, child: User) -> str:
    return f"{task.title} returned to {child.name}."
