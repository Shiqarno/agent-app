from app.models import User, UserRole

NO_USERS_TEXT = "Пользователей пока нет."

_ROLE_LABELS = {
    UserRole.ADULT: "Взрослый",
    UserRole.CHILD: "Ребёнок",
}


def _connection_label(connected: bool) -> str:
    return "Подключён" if connected else "Не подключён"


def render_users_list(items: list[tuple[User, bool]]) -> str:
    """Issue #29 section 2 / Issue #37: just the heading -- every User
    always has a button (users_list_keyboard), showing their name, so
    nothing is duplicated as separate text above it. Role and connection
    status, when needed, live one tap further in on User Details
    (render_user_details below), a selected-entity screen.
    """
    if not items:
        return f"Пользователи\n\n{NO_USERS_TEXT}"
    return "Пользователи"


def render_user_details(user: User, connected: bool) -> str:
    return f"{user.name}\n\n{_ROLE_LABELS[user.role]}\nTelegram: {_connection_label(connected)}"


def render_add_child_prompt() -> str:
    return "Как зовут ребёнка?"


def render_child_created(name: str, link: str) -> str:
    return (
        f"Профиль «{name}» создан.\n\n"
        f"Отправьте {name} эту ссылку для активации:\n\n"
        f"{link}\n\n"
        "Ссылка действительна 72 часа."
    )


def render_activation_link(link: str) -> str:
    return f"Ссылка для активации:\n\n{link}\n\nСсылка действительна 72 часа."
