from app.models import Task, TaskExecution, TaskExecutionStatus, User

ALL_TASKS_HEADING = "Все задачи"
NO_TASKS_TEXT = "No tasks yet."
NO_ELIGIBLE_CHILDREN_TEXT = "No eligible children right now."

_EXECUTION_STATE_LABELS = {
    TaskExecutionStatus.ASSIGNED: "assigned",
    TaskExecutionStatus.IN_PROGRESS: "in progress",
    TaskExecutionStatus.AWAITING_CONFIRMATION: "waiting for confirmation",
}


def _execution_summary(execution: TaskExecution, child: User) -> str:
    return f"{child.name} — {_EXECUTION_STATE_LABELS[execution.status]}"


def render_tasks_list(items: list[tuple[Task, TaskExecution | None, User | None]]) -> str:
    """Issue #28 section 4 / Issue #36: just the heading -- every Task
    always has its own button (tasks_list_keyboard), which already shows
    name, reward, and self-claim availability (via strikethrough), so
    nothing is duplicated as separate text above it. The current open
    execution's Child and state, when one exists, remains visible one tap
    further in on Task Details (render_task_details below), which is a
    selected-entity screen, not a list.
    """
    if not items:
        return f"{ALL_TASKS_HEADING}\n\n{NO_TASKS_TEXT}"
    return ALL_TASKS_HEADING


def render_task_details(task: Task, execution: TaskExecution | None, child: User | None) -> str:
    """Issue #28 section 5. With a current open execution, only Edit is
    unavailable (Issue #37: Activate/Deactivate are never blocked by an
    open execution, since toggling the self-claim slot doesn't touch it)
    -- this view never becomes a confirmation UI; that stays in the
    separate Confirmation workflow. Status is always shown, execution or
    not: `is_active` is independent of any execution (a directly-assigned
    or reactivated Task can be Available with one open), so it would be
    misleading to hide it whenever an execution happens to exist.
    """
    header = f"{task.title}\n\nReward: {task.reward_points} points"
    status = "Available" if task.is_active else "Not available"
    if execution is not None and child is not None:
        return (
            f"{header}\nStatus: {status}\n\n{_execution_summary(execution, child)}\n\n"
            "Cannot edit the name or reward while this execution is open."
        )
    return f"{header}\nStatus: {status}"


def render_create_prompt_title() -> str:
    return "What's the task called?"


def render_create_prompt_reward() -> str:
    return "How many points is it worth?"


def render_edit_menu(task: Task) -> str:
    return f"Edit task\n\nCurrent name:\n{task.title}\n\nCurrent reward:\n{task.reward_points}"


def render_edit_prompt_title(task: Task) -> str:
    return f"Current name:\n{task.title}\n\nSend the new name."


def render_edit_prompt_reward(task: Task) -> str:
    return f"Current reward:\n{task.reward_points}\n\nSend the new reward, in points."


def render_assign_children(task: Task, children: list[User]) -> str:
    """Issue #32 "Adult UX": the eligible-Children screen behind Task
    Details' Assign action -- makes the reason for an empty list clear
    rather than showing a bare empty screen.
    """
    header = f"Assign · {task.title}"
    if not children:
        return f"{header}\n\n{NO_ELIGIBLE_CHILDREN_TEXT}"
    return f"{header}\n\nChoose a child:"


def render_task_assigned(task: Task, child: User) -> str:
    return f"{task.title} assigned to {child.name}."
