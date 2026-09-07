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
    only, the Application layer refuses the action regardless.
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
    rows.append([InlineKeyboardButton("← Tasks", callback_data=LIST_CALLBACK_DATA)])
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
