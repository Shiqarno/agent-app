from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import Task, TaskExecution, User

CONFIRM_CALLBACK_PREFIX = "confirmation:confirm:"
RETURN_CALLBACK_PREFIX = "confirmation:return:"
VIEW_ALL_CALLBACK_DATA = "confirmation:list"
OPEN_CALLBACK_PREFIX = "confirmation:open:"


def confirmation_list_keyboard(
    items: list[tuple[TaskExecution, Task, User]],
) -> InlineKeyboardMarkup:
    """One row per execution, Task name + Child name (Issue #36 step 1) --
    the Child name disambiguates when multiple Children have an execution
    of the same Task, which a title-only button could not. Confirm and
    Return live one tap further in, on the selected execution's own
    detail screen (confirmation_detail_keyboard), not here. The callback
    payload only identifies the execution for routing, never authorization;
    the Application layer re-verifies everything.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{task.title} · {child.name}",
                callback_data=f"{OPEN_CALLBACK_PREFIX}{execution.id}",
            )
        ]
        for execution, task, child in items
    ]
    return InlineKeyboardMarkup(rows)


def confirmation_detail_keyboard(execution: TaskExecution) -> InlineKeyboardMarkup:
    """Confirm/Return for exactly the selected execution (Issue #36 step 2)
    -- no title needed on these buttons, since the detail screen above them
    already names the Task. `← Back` reuses the existing list callback
    (Issue #25's `VIEW_ALL_CALLBACK_DATA`) rather than a new one.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Confirm", callback_data=f"{CONFIRM_CALLBACK_PREFIX}{execution.id}"
                ),
                InlineKeyboardButton(
                    "Return", callback_data=f"{RETURN_CALLBACK_PREFIX}{execution.id}"
                ),
            ],
            [InlineKeyboardButton("← Back", callback_data=VIEW_ALL_CALLBACK_DATA)],
        ]
    )
