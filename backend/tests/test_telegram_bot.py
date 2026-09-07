import pytest

from app.config import settings
from app.telegram.bot import build_application
from app.telegram.handlers.confirmations import (
    handle_confirm_execution,
    handle_confirmations_command,
    handle_return_execution,
    handle_view_all_confirmations,
)
from app.telegram.handlers.rewards import handle_get_reward, handle_rewards_command
from app.telegram.handlers.start import handle_start
from app.telegram.handlers.tasks import (
    handle_mark_ready,
    handle_my_tasks_command,
    handle_take_task,
    handle_tasks_command,
)


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
    assert handle_rewards_command in callbacks
    assert handle_get_reward in callbacks


def test_build_application_fails_clearly_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", None)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        build_application()
