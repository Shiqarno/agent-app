import asyncio

import pytest

from app.config import settings
from app.telegram import bot as bot_module
from app.telegram.bot import build_application
from app.telegram.handlers.adult_points import (
    handle_adjust_menu,
    handle_list_children,
    handle_older_child_points,
    handle_open_child_points,
    handle_points_home,
    handle_start_add,
    handle_start_remove,
)
from app.telegram.handlers.adult_points import (
    handle_points_command as handle_points_command_dispatch,
)
from app.telegram.handlers.adult_rewards import (
    handle_add_reward,
    handle_open_reward,
)
from app.telegram.handlers.adult_rewards import (
    handle_edit_reward as handle_edit_reward_entry,
)
from app.telegram.handlers.adult_rewards import (
    handle_list_rewards as handle_list_rewards_catalog,
)
from app.telegram.handlers.adult_rewards import (
    handle_rewards_command as handle_rewards_command_dispatch,
)
from app.telegram.handlers.adult_rewards import (
    handle_rewards_home as handle_rewards_home_catalog,
)
from app.telegram.handlers.adult_tasks import (
    handle_activate_task,
    handle_add_task,
    handle_deactivate_task,
    handle_edit_menu,
    handle_edit_name,
    handle_edit_reward,
    handle_home,
    handle_list_tasks,
    handle_open_task,
    handle_tasks_command,
)
from app.telegram.handlers.adult_users import (
    handle_add_child,
    handle_get_activation_link,
    handle_list_users,
    handle_open_user,
    handle_users_command,
    handle_users_home,
)
from app.telegram.handlers.confirmations import (
    handle_confirm_execution,
    handle_confirmations_command,
    handle_return_execution,
    handle_view_all_confirmations,
)
from app.telegram.handlers.points import handle_older_points
from app.telegram.handlers.rewards import handle_get_reward
from app.telegram.handlers.start import handle_start
from app.telegram.handlers.tasks import handle_mark_ready, handle_my_tasks_command, handle_take_task


@pytest.fixture
def fake_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing an Application never makes a network call (that starts
    with run_polling(), never invoked here), so a syntactically-plausible
    fake token is enough -- no real Telegram connectivity needed.
    """
    monkeypatch.setattr(settings, "telegram_bot_token", "123456:fake-token-for-tests")


def test_build_application_registers_every_handler(fake_token: None) -> None:
    application = build_application()

    callbacks = {handler.callback for group in application.handlers.values() for handler in group}

    assert handle_start in callbacks
    assert handle_tasks_command in callbacks
    assert handle_my_tasks_command in callbacks
    assert handle_take_task in callbacks
    assert handle_mark_ready in callbacks
    assert handle_confirmations_command in callbacks
    assert handle_confirm_execution in callbacks
    assert handle_return_execution in callbacks
    assert handle_view_all_confirmations in callbacks
    assert handle_rewards_command_dispatch in callbacks
    assert handle_get_reward in callbacks
    assert handle_points_command_dispatch in callbacks
    assert handle_older_points in callbacks
    assert handle_open_child_points in callbacks
    assert handle_list_children in callbacks
    assert handle_points_home in callbacks
    assert handle_older_child_points in callbacks
    assert handle_adjust_menu in callbacks
    assert handle_start_add in callbacks
    assert handle_start_remove in callbacks
    assert handle_open_task in callbacks
    assert handle_list_tasks in callbacks
    assert handle_home in callbacks
    assert handle_add_task in callbacks
    assert handle_edit_menu in callbacks
    assert handle_edit_name in callbacks
    assert handle_edit_reward in callbacks
    assert handle_activate_task in callbacks
    assert handle_deactivate_task in callbacks
    assert handle_users_command in callbacks
    assert handle_open_user in callbacks
    assert handle_list_users in callbacks
    assert handle_users_home in callbacks
    assert handle_add_child in callbacks
    assert handle_get_activation_link in callbacks
    assert handle_open_reward in callbacks
    assert handle_list_rewards_catalog in callbacks
    assert handle_rewards_home_catalog in callbacks
    assert handle_add_reward in callbacks
    assert handle_edit_reward_entry in callbacks
    assert bot_module._handle_text_input in callbacks


def test_build_application_fails_clearly_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", None)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        build_application()


# =========================================================================================
# Shared free-text dispatch (Issue #29): only one generic-text MessageHandler
# can ever fire per update, so it must route to whichever feature's flow is
# currently open, based on which context.user_data flow key is present.
# =========================================================================================


class _FakeContext:
    def __init__(self, user_data: dict[str, object]) -> None:
        self.user_data = user_data


def _patch_all_flow_handlers(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    async def fake_task_handler(update: object, context: object) -> None:
        calls.append("task")

    async def fake_user_handler(update: object, context: object) -> None:
        calls.append("user")

    async def fake_reward_handler(update: object, context: object) -> None:
        calls.append("reward")

    async def fake_points_handler(update: object, context: object) -> None:
        calls.append("points")

    monkeypatch.setattr(bot_module.adult_tasks, "handle_task_flow_text", fake_task_handler)
    monkeypatch.setattr(bot_module.adult_users, "handle_user_flow_text", fake_user_handler)
    monkeypatch.setattr(bot_module.adult_rewards, "handle_reward_flow_text", fake_reward_handler)
    monkeypatch.setattr(bot_module.adult_points, "handle_points_flow_text", fake_points_handler)


def test_text_input_dispatches_to_the_open_task_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_all_flow_handlers(monkeypatch, calls)

    context = _FakeContext(user_data={bot_module.adult_tasks._FLOW_KEY: {}})
    asyncio.run(bot_module._handle_text_input(None, context))  # type: ignore[arg-type]

    assert calls == ["task"]


def test_text_input_dispatches_to_the_open_user_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_all_flow_handlers(monkeypatch, calls)

    context = _FakeContext(user_data={bot_module.adult_users._FLOW_KEY: {}})
    asyncio.run(bot_module._handle_text_input(None, context))  # type: ignore[arg-type]

    assert calls == ["user"]


def test_text_input_dispatches_to_the_open_reward_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_all_flow_handlers(monkeypatch, calls)

    context = _FakeContext(user_data={bot_module.adult_rewards._FLOW_KEY: {}})
    asyncio.run(bot_module._handle_text_input(None, context))  # type: ignore[arg-type]

    assert calls == ["reward"]


def test_text_input_dispatches_to_the_open_points_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_all_flow_handlers(monkeypatch, calls)

    context = _FakeContext(user_data={bot_module.adult_points._FLOW_KEY: {}})
    asyncio.run(bot_module._handle_text_input(None, context))  # type: ignore[arg-type]

    assert calls == ["points"]


def test_text_input_does_nothing_with_no_active_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_all_flow_handlers(monkeypatch, calls)

    context = _FakeContext(user_data={})
    asyncio.run(bot_module._handle_text_input(None, context))  # type: ignore[arg-type]

    assert calls == []
