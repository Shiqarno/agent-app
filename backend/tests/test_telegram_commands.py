from app.models import UserRole
from app.telegram.commands import (
    ADULT_COMMANDS,
    CHILD_COMMANDS,
    DEFAULT_COMMANDS,
    commands_for_role,
)

_ADULT_ONLY = {"users", "confirmations"}
_CHILD_ONLY = {"mytasks"}


def _names(commands: list[object]) -> set[str]:
    return {c.command for c in commands}  # type: ignore[attr-defined]


def test_child_command_panel_has_the_expected_commands() -> None:
    names = _names(CHILD_COMMANDS)

    assert names == {"start", "tasks", "mytasks", "rewards", "points"}


def test_adult_command_panel_has_the_expected_commands() -> None:
    names = _names(ADULT_COMMANDS)

    assert names == {"start", "users", "tasks", "confirmations", "rewards", "points"}


def test_child_panel_never_exposes_adult_only_commands() -> None:
    names = _names(CHILD_COMMANDS)

    assert names.isdisjoint(_ADULT_ONLY)


def test_adult_panel_never_exposes_child_only_navigation_commands() -> None:
    names = _names(ADULT_COMMANDS)

    assert names.isdisjoint(_CHILD_ONLY)


def test_both_panels_share_the_start_home_command() -> None:
    assert "start" in _names(CHILD_COMMANDS)
    assert "start" in _names(ADULT_COMMANDS)


def test_commands_for_role_returns_the_child_panel() -> None:
    assert commands_for_role(UserRole.CHILD) == CHILD_COMMANDS


def test_commands_for_role_returns_the_adult_panel() -> None:
    assert commands_for_role(UserRole.ADULT) == ADULT_COMMANDS


def test_default_commands_only_offer_start() -> None:
    assert _names(DEFAULT_COMMANDS) == {"start"}
