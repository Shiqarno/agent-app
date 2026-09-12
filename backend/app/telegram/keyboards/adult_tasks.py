import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, User
from app.telegram.keyboards.adult_points import encode_uuid

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
# Shortened from the more descriptive `assignchild` (Issue:
# `Button_data_invalid`): with two packed UUIDs in the payload (see
# assign_children_keyboard below), the longer prefix pushed the total
# callback_data past Telegram's 64-byte limit.
ASSIGN_TO_CALLBACK_PREFIX = "adulttask:assignto:"


def _task_button_label(task: Task) -> str:
    """An active Task shows its name and current reward (Issue #35); an
    inactive one shows its plain name prefixed with `❌`, no reward at all
    (Issue #37/#38) -- the button represents an unavailable self-claim
    offer, not a reward-bearing action, so showing a reward on it would be
    misleading. Driven by `is_active` alone, never by whether a current
    execution exists, matching this Task's own established, execution-
    independent meaning (Issue #32).
    """
    if task.is_active:
        return f"{task.title} · 💰 {task.reward_points}"
    return f"❌ {task.title}"


def tasks_list_keyboard(
    items: list[tuple[Task, TaskExecution | None, User | None]],
) -> InlineKeyboardMarkup:
    """One row per Task, plus `+ Add task` and `← Home` (Issue #28 section
    4). Each button shows name and reward so the Adult doesn't need to
    open every Task to see them (Issue #35); self-claim availability is
    shown via `_task_button_label` above rather than a separate
    `Available`/`Unavailable` word (Issue #36/#37). The callback payload
    only identifies the Task for routing -- the Application layer
    re-verifies role/existence/state on every call.
    """
    rows = [
        [
            InlineKeyboardButton(
                _task_button_label(task), callback_data=f"{OPEN_CALLBACK_PREFIX}{task.id}"
            )
        ]
        for task, _execution, _child in items
    ]
    rows.append([InlineKeyboardButton("+ Добавить задачу", callback_data=ADD_CALLBACK_DATA)])
    rows.append([InlineKeyboardButton("← Домой", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def task_details_keyboard(task: Task, has_current_execution: bool) -> InlineKeyboardMarkup:
    """`Edit` only when there is no current open execution (Issue #28
    section 5, unchanged) -- hiding the button is presentation only, the
    Application layer refuses the action regardless. `Activate`/
    `Deactivate` are always available (Issue #37): toggling the self-claim
    slot never touches existing executions, so it's never blocked by them.
    `Assign` (Issue #32) is likewise always available, current execution
    or not: direct assignment is independent of `Task.is_active` and of
    any other Child's open execution -- a Task may have any number of open
    executions for different Children simultaneously.
    """
    rows = []
    if not has_current_execution:
        rows.append(
            [InlineKeyboardButton("Изменить", callback_data=f"{EDIT_CALLBACK_PREFIX}{task.id}")]
        )
    if task.is_active:
        rows.append(
            [
                InlineKeyboardButton(
                    "Деактивировать", callback_data=f"{DEACTIVATE_CALLBACK_PREFIX}{task.id}"
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "Активировать", callback_data=f"{ACTIVATE_CALLBACK_PREFIX}{task.id}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("Назначить", callback_data=f"{ASSIGN_CALLBACK_PREFIX}{task.id}")]
    )
    rows.append([InlineKeyboardButton("← Задачи", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def assign_children_keyboard(task_id: uuid.UUID, children: list[User]) -> InlineKeyboardMarkup:
    """One row per eligible Child (Issue #32 "Adult UX") -- the callback
    payload only identifies the Task and Child for routing; the
    Application layer re-verifies eligibility on every call.

    Both ids are packed via `encode_uuid` (not the 36-char hyphenated form,
    reused from the Adult Points pagination fix): unpacked, `task_id` +
    `:` + `child.id` alone would already exceed Telegram's 64-byte
    callback_data limit (Issue: `Button_data_invalid` on Task Assign).
    """
    encoded_task_id = encode_uuid(task_id)
    rows = [
        [
            InlineKeyboardButton(
                child.name,
                callback_data=f"{ASSIGN_TO_CALLBACK_PREFIX}{encoded_task_id}:"
                f"{encode_uuid(child.id)}",
            )
        ]
        for child in children
    ]
    rows.append([InlineKeyboardButton("← Назад", callback_data=f"{OPEN_CALLBACK_PREFIX}{task_id}")])
    return InlineKeyboardMarkup(rows)


def edit_menu_keyboard(task: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Изменить название", callback_data=f"{EDIT_NAME_CALLBACK_PREFIX}{task.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "Изменить награду", callback_data=f"{EDIT_REWARD_CALLBACK_PREFIX}{task.id}"
                )
            ],
            [InlineKeyboardButton("← Задачи", callback_data=LIST_CALLBACK_DATA)],
        ]
    )


def back_to_tasks_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a Task/action can't be shown at all (not
    found, or input was invalid) -- the user must never be stranded
    (Issue #28 section 17).
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Задачи", callback_data=LIST_CALLBACK_DATA)]]
    )
