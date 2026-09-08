from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import User, UserRole

OPEN_CALLBACK_PREFIX = "adultuser:open:"
ADD_CHILD_CALLBACK_DATA = "adultuser:add"
LIST_CALLBACK_DATA = "adultuser:list"
HOME_CALLBACK_DATA = "adultuser:home"
GET_LINK_CALLBACK_PREFIX = "adultuser:getlink:"


def users_list_keyboard(items: list[tuple[User, bool]]) -> InlineKeyboardMarkup:
    """One row per User, plus `+ Add Child` and `← Home` (Issue #29 section
    2). The button label is just the User's name (Issue #37) -- matching
    every other Adult list in this app, the button *is* the User, so no
    action-verb prefix or separate name text is needed. The callback
    payload only identifies the User for routing -- the Application layer
    re-verifies role/existence/state on every call.
    """
    rows = [
        [InlineKeyboardButton(user.name, callback_data=f"{OPEN_CALLBACK_PREFIX}{user.id}")]
        for user, _connected in items
    ]
    rows.append([InlineKeyboardButton("+ Add Child", callback_data=ADD_CHILD_CALLBACK_DATA)])
    rows.append([InlineKeyboardButton("← Home", callback_data=HOME_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def user_details_keyboard(user: User, connected: bool) -> InlineKeyboardMarkup:
    """`Get activation link` only for a Child who isn't yet connected
    (Issue #29 section 6/7) -- never exposed for a connected User, and
    never a reconnect mechanism. Hiding the button is presentation only;
    the Application layer refuses the operation regardless.
    """
    rows = []
    if user.role == UserRole.CHILD and not connected:
        rows.append(
            [
                InlineKeyboardButton(
                    "Get activation link", callback_data=f"{GET_LINK_CALLBACK_PREFIX}{user.id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("← Users", callback_data=LIST_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


def back_to_users_keyboard() -> InlineKeyboardMarkup:
    """A minimal way back when a User/action can't be shown at all (not
    found, or input was invalid) -- the Adult must never be stranded.
    """
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("← Users", callback_data=LIST_CALLBACK_DATA)]]
    )
