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


def render_task_list_item(task: Task, execution: TaskExecution | None, child: User | None) -> str:
    """Issue #28 section 4: name, reward, availability, and -- only when
    one exists -- the current open execution's Child and state. Never
    execution history.
    """
    if execution is not None and child is not None:
        availability = f"Not available\n{_execution_summary(execution, child)}"
    elif task.is_active:
        availability = "Available"
    else:
        availability = "Not available"
    return f"{task.title}\n{task.reward_points} points\n{availability}"


def render_tasks_list(items: list[tuple[Task, TaskExecution | None, User | None]]) -> str:
    if not items:
        return f"{ALL_TASKS_HEADING}\n\n{NO_TASKS_TEXT}"
    blocks = [render_task_list_item(task, execution, child) for task, execution, child in items]
    return f"{ALL_TASKS_HEADING}\n\n" + "\n\n".join(blocks)


def render_task_details(task: Task, execution: TaskExecution | None, child: User | None) -> str:
    """Issue #28 section 5. With a current open execution, Edit/Activate/
    Deactivate are all unavailable -- this view never becomes a
    confirmation UI; that stays in the separate Confirmation workflow.
    """
    header = f"{task.title}\n\nReward: {task.reward_points} points"
    if execution is not None and child is not None:
        return f"{header}\n\n{_execution_summary(execution, child)}\n\nTask currently unavailable."
    status = "Available" if task.is_active else "Not available"
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
