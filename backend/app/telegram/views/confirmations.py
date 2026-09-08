from app.models import Task, TaskExecution, User

CONFIRMATIONS_HEADING = "Подтверждения"
NO_CONFIRMATIONS_TEXT = "No tasks waiting for confirmation."


def render_confirmation_list(items: list[tuple[TaskExecution, Task, User]]) -> str:
    """Issue #36 step 1: just the heading -- each execution's Task name
    lives only on its own button (confirmation_list_keyboard), never
    duplicated as a separate text block above it.
    """
    if not items:
        return f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    return CONFIRMATIONS_HEADING


def render_confirmation_detail(execution: TaskExecution, task: Task, child: User) -> str:
    """Issue #36 step 2: the selected execution's own Task name, Child, and
    reward snapshot -- shown once here, not on the Confirm/Return buttons
    beneath it (confirmation_detail_keyboard).
    """
    return f"{task.title}\n\n{child.name} · {execution.reward_points} pts"


def render_execution_confirmed(task: Task, child: User, execution: TaskExecution) -> str:
    return f"{task.title} confirmed -- {child.name} earned {execution.reward_points} pts."


def render_execution_returned(task: Task, child: User) -> str:
    return f"{task.title} returned to {child.name}."
