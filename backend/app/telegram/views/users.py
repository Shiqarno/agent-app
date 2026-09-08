from app.models import User

NO_USERS_TEXT = "No users yet."


def _connection_label(connected: bool) -> str:
    return "Connected" if connected else "Not connected"


def render_users_list(items: list[tuple[User, bool]]) -> str:
    """Issue #29 section 2 / Issue #37: just the heading -- every User
    always has a button (users_list_keyboard), showing their name, so
    nothing is duplicated as separate text above it. Role and connection
    status, when needed, live one tap further in on User Details
    (render_user_details below), a selected-entity screen.
    """
    if not items:
        return f"Users\n\n{NO_USERS_TEXT}"
    return "Users"


def render_user_details(user: User, connected: bool) -> str:
    return (
        f"{user.name}\n\n{user.role.value.capitalize()}\nTelegram: {_connection_label(connected)}"
    )


def render_add_child_prompt() -> str:
    return "What's the Child's name?"


def render_child_created(name: str, link: str) -> str:
    return (
        f"{name} was created.\n\n"
        f"Send this activation link to {name}:\n\n"
        f"{link}\n\n"
        "The link expires in 72 hours."
    )


def render_activation_link(link: str) -> str:
    return f"Activation link:\n\n{link}\n\nThe link expires in 72 hours."
