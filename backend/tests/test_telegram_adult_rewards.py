import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.models import Reward, TelegramIdentity, User, UserActivation, UserRole
from app.telegram.handlers.adult_rewards import (
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _REWARD_NOT_FOUND_TEXT,
    _finish_create,
    _finish_edit,
    _reward_details_view,
    _rewards_command_view,
    _rewards_list_view,
    _route_flow_text,
    _start_create,
    _start_edit,
)
from app.telegram.keyboards.adult_rewards import EDIT_CALLBACK_PREFIX, OPEN_CALLBACK_PREFIX
from app.telegram_identity import activate_telegram_identity

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


class RealData:
    """Same rationale as the other test_telegram_*.py RealData helpers: the
    handlers under test open their own `SessionLocal()`, a genuinely
    separate, independently-committing connection from the savepoint-
    isolated `db_session` fixture, so setup here must use a real session too.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.user_ids: list[uuid.UUID] = []
        self.reward_ids: list[uuid.UUID] = []

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    def make_reward(
        self,
        creator: User,
        *,
        name: str = "Ice cream",
        description: str | None = "Vanilla or chocolate",
        cost_points: int = 100,
    ) -> Reward:
        reward = Reward(
            name=name, description=description, cost_points=cost_points, created_by=creator.id
        )
        self.session.add(reward)
        self.session.commit()
        self.session.refresh(reward)
        self.reward_ids.append(reward.id)
        return reward

    def connect_via_activation(self, user: User, telegram_id: int) -> None:
        token = insert_activation(self.session, user.id)
        self.session.commit()
        activate_telegram_identity(self.session, token, telegram_id)


@pytest.fixture
def real(db_session: Session) -> Iterator[RealData]:
    del db_session
    session = SessionLocal()
    data = RealData(session)
    try:
        yield data
    finally:
        session.rollback()
        if data.reward_ids:
            session.query(Reward).filter(Reward.id.in_(data.reward_ids)).delete(
                synchronize_session=False
            )
        if data.user_ids:
            session.query(TelegramIdentity).filter(
                TelegramIdentity.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
            session.query(UserActivation).filter(UserActivation.user_id.in_(data.user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(data.user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


# =========================================================================================
# List
# =========================================================================================


def test_adult_can_open_rewards(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    real.make_reward(adult, name="Pizza", cost_points=500)

    text, keyboard = _rewards_command_view(telegram_id)

    assert "Pizza" in text
    assert "500" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Pizza" in label for label in labels)
    assert any("Add Reward" in label for label in labels)


def test_child_rewards_command_still_opens_child_redemption_screen(real: RealData) -> None:
    """Regression: /rewards must remain the existing Child redemption
    screen for a Child, unaffected by the new Adult dispatch.
    """
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)
    real.make_reward(child, name="Pizza", cost_points=500)

    text, keyboard = _rewards_command_view(telegram_id)

    # The Child redemption view ("Доступные награды\nYou have N points...")
    # is distinct from the Adult catalog-management view ("🎁 Rewards...").
    assert text.startswith("Доступные награды\nYou have")
    assert "Pizza" in text
    assert keyboard is not None


def test_child_cannot_open_adult_rewards_management(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, keyboard = _rewards_list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_rewards_view_for_unconnected_account() -> None:
    text, keyboard = _rewards_command_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Details
# =========================================================================================


def test_adult_can_open_reward_details(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    reward = real.make_reward(
        adult, name="Pizza", description="Pizza of your choice.", cost_points=500
    )

    text, keyboard = _reward_details_view(telegram_id, str(reward.id))

    assert "Pizza" in text
    assert "500" in text
    assert "Pizza of your choice." in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "Edit" in labels
    assert not any("Delete" in label for label in labels)
    assert not any("Deactivate" in label or "Activate" in label for label in labels)


def test_open_nonexistent_reward_does_not_strand_the_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, keyboard = _reward_details_view(telegram_id, str(uuid.uuid4()))

    assert text == _REWARD_NOT_FOUND_TEXT
    assert keyboard is not None


def test_child_cannot_open_reward_details_via_crafted_callback(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child_actor = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child_actor, telegram_id)
    reward = real.make_reward(adult)

    text, keyboard = _reward_details_view(telegram_id, str(reward.id))

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Add Reward
# =========================================================================================


def test_start_create_prompts_for_name(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is True
    assert "called" in text.lower()


def test_child_cannot_start_add_reward(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is False
    assert text == _NOT_AN_ADULT_TEXT


def test_add_reward_flow_collects_name_then_cost_then_description(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    flow: dict[str, object] = {"action": "create_reward", "step": "name"}

    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "Pizza")
    assert finished is False
    assert flow["step"] == "cost"
    assert "points" in text.lower() or "cost" in text.lower()

    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "500")
    assert finished is False
    assert flow["step"] == "description"
    assert "description" in text.lower()

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "Pizza of your choice.")
    assert finished is True
    assert "Pizza was created." in text
    assert keyboard is not None

    created = real.session.query(Reward).filter_by(name="Pizza").one()
    real.reward_ids.append(created.id)
    assert created.cost_points == 500
    assert created.description == "Pizza of your choice."


def test_add_reward_accepts_an_empty_description_via_skip(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, _keyboard = _finish_create(telegram_id, "Movie night", 300, None)

    assert "Movie night was created." in text
    created = real.session.query(Reward).filter_by(name="Movie night").one()
    real.reward_ids.append(created.id)
    assert created.description is None


def test_add_reward_invalid_cost_does_not_create_a_reward(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    flow: dict[str, object] = {"action": "create_reward", "step": "cost", "name": "Pizza"}
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "not a number")

    assert finished is False
    assert "whole number" in text.lower()
    assert real.session.query(Reward).filter_by(name="Pizza").count() == 0


def test_add_reward_via_crafted_flow_state_rejects_a_child_actor(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child, telegram_id)

    text, _keyboard = _finish_create(telegram_id, "Hacked", 100, None)

    assert text == _NOT_AN_ADULT_TEXT
    assert real.session.query(Reward).filter_by(name="Hacked").count() == 0


# =========================================================================================
# Edit Reward
# =========================================================================================


def test_adult_can_start_editing_a_reward(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    reward = real.make_reward(adult, name="Pizza")

    text, should_start, keyboard = _start_edit(telegram_id, str(reward.id))

    assert should_start is True
    assert "Pizza" in text
    assert keyboard is None


def test_edit_reward_end_to_end_updates_name_cost_and_description(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    reward = real.make_reward(adult, name="Pizza", description="Old", cost_points=500)

    text, keyboard = _finish_edit(
        telegram_id, str(reward.id), "Deluxe Pizza", 600, "New description"
    )

    assert "Deluxe Pizza was updated." in text
    assert keyboard is not None
    real.session.refresh(reward)
    assert reward.name == "Deluxe Pizza"
    assert reward.cost_points == 600
    assert reward.description == "New description"


def test_edit_reward_skip_on_description_keeps_it_unchanged(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)
    reward = real.make_reward(adult, name="Pizza", description="Original description")

    flow: dict[str, object] = {
        "action": "edit_reward",
        "step": "description",
        "reward_id": str(reward.id),
        "name": "Pizza",
        "cost_points": 500,
    }
    text, _keyboard, finished = _route_flow_text(telegram_id, flow, "skip")

    assert finished is True
    assert "was updated" in text
    real.session.refresh(reward)
    assert reward.description == "Original description"


def test_edit_missing_reward_is_handled_safely(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(adult, telegram_id)

    text, should_start, keyboard = _start_edit(telegram_id, str(uuid.uuid4()))

    assert should_start is False
    assert text == _REWARD_NOT_FOUND_TEXT
    assert keyboard is not None


def test_edit_reward_child_cannot_bypass_via_crafted_callback(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child_actor = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect_via_activation(child_actor, telegram_id)
    reward = real.make_reward(adult, name="Pizza")

    text, _keyboard = _finish_edit(telegram_id, str(reward.id), "Hacked", 999, None)

    assert text == _NOT_AN_ADULT_TEXT
    real.session.refresh(reward)
    assert reward.name == "Pizza"


# =========================================================================================
# Callback payload sanity
# =========================================================================================


def test_open_and_edit_callback_prefixes_do_not_collide() -> None:
    assert not "adultreward:edit:123".startswith(OPEN_CALLBACK_PREFIX)
    assert not "adultreward:open:123".startswith(EDIT_CALLBACK_PREFIX)
