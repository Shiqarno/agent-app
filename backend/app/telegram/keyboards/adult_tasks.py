import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, User

OPEN_CALLBACK_PREFIX = "adulttask:open:"
ADD_CALLBACK_DATA = "adulttask:add"
LIST_CALLBACK_DATA = "adulttask:list"
HOME_CALLBACK_DATA = "adulttask:home"
EDIT_CALLBACK_PREFIX = "adulttask:edit:"
EDIT_NAME_CALLBACK_PREFIX = "adulttask:editname:"
EDIT_REWARD_CALLBACK_PREFIX = "adulttask:editreward:"
ACTIVATE_CALLBACK_PREFIX = "adulttask:activate:"
DEACTIVATE_CALLBACK_PREFIX = "adulttask:deactivate:"
ASSIGN_CALLBACK_PREFIX = "adulttask:assign:"
ASSIGN_TO_CALLBACK_PREFIX = "adulttask:assignchild:"


def tasks_list_keyboard(
    items: list[tuple[Task, TaskExecution | None, User | None]],
) -> InlineKeyboardMarkup:
    """One `Open` row per Task, plus `+ Add task` and `← Home` (Issue #28
    section 4). The callback payload only identifies the Task for routing
    -- the Application layer re-verifies role/existence/state on every call.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"Open · {task.title}", callback_data=f"{OPEN_CALLBACK_PREFIX}{task.id}"
            )
        ]
        for task, _, _ in items
    ]
    rows.append([InlineKeyboardButton("+ Add task", callback_data=ADD_CALLBACK_DATA)])
    rows.append([InlineKeyboardButton("← Home", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def task_details_keyboard(task: Task, has_current_execution: bool) -> InlineKeyboardMarkup:
    """Edit/Activate/Deactivate only when there is no current open
    execution (Issue #28 section 5) -- hiding the button is presentation
    only, the Application layer refuses the action regardless. `Assign`
    (Issue #32) is deliberately always available, current execution or
    not: direct assignment is independent of `Task.is_active` and of any
    other Child's open execution -- a Task may have any number of open
    executions for different Children simultaneously.
    """
    rows = []
    if not has_current_execution:
        rows.append(
            [InlineKeyboardButton("Edit", callback_data=f"{EDIT_CALLBACK_PREFIX}{task.id}")]
        )
        if task.is_active:
            rows.append(
                [
                    InlineKeyboardButton(
                        "Deactivate", callback_data=f"{DEACTIVATE_CALLBACK_PREFIX}{task.id}"
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        "Activate", callback_data=f"{ACTIVATE_CALLBACK_PREFIX}{task.id}"
                    )
                ]
            )
    rows.append(
        [InlineKeyboardButton("Assign", callback_data=f"{ASSIGN_CALLBACK_PREFIX}{task.id}")]
    )
    rows.append([InlineKeyboardButton("← Tasks", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def assign_children_keyboard(task_id: uuid.UUID, children: list[User]) -> InlineKeyboardMarkup:
    """One row per eligible Child (Issue #32 "Adult UX") -- the callback
    payload only identifies the Task and Child for routing; the
    Application layer re-verifies eligibility on every call.
    """
    rows = [
        [
            InlineKeyboardButton(
                child.name, callback_data=f"{ASSIGN_TO_CALLBACK_PREFIX}{task_id}:{child.id}"
            )
        ]
        for child in children
    ]
    rows.append([InlineKeyboardButton("← Back", callback_data=f"{OPEN_CALLBACK_PREFIX}{task_id}")])
    return InlineKeyboardMarkup(rows)


def edit_menu_keyboard(task: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Change name", callback_data=f"{EDIT_NAME_CALLBACK_PREFIX}{task.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Change reward", callback_data=f"{EDIT_REWARD_CALLBACK_PREFIX}{task.id}"
                )
            ],
            [InlineKeyboardButton("← Tasks", callback_data=LIST_CALLBACK_DATA)],
        ]
    )


def back_to_tasks_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Task/action can't be shown at all (not
    found, or input was invalid) -- the user must never be stranded
    (Issue #28 section 17).
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Tasks", callback_data=LIST_CALLBACK_DATA)]]
    )
