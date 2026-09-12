import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.db import SessionLocal
from app.goal_operations import PAGE_SIZE
from app.models import (
    Goal,
    GoalContribution,
    GoalStatus,
    PointTransaction,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.handlers.adult_goals import (
    _GOAL_NOT_EDITABLE_TEXT,
    _GOAL_NOT_FOUND_TEXT,
    _NOT_AN_ADULT_TEXT,
    _NOT_CONNECTED_TEXT,
    _adult_goals_list_view,
    _finish_create,
    _finish_edit_cost,
    _finish_edit_name,
    _goal_details_view,
    _goals_command_view,
    _route_flow_text,
    _start_create,
    _start_edit_field,
    _start_edit_menu,
)
from app.telegram.keyboards.adult_goals import (
    ADD_CALLBACK_DATA,
    EDIT_CALLBACK_PREFIX,
    EDIT_COST_CALLBACK_PREFIX,
    EDIT_NAME_CALLBACK_PREFIX,
    HOME_CALLBACK_DATA,
    LIST_CALLBACK_DATA,
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    decode_older_payload,
)
from app.telegram.views.adult_goals import NO_GOALS_TEXT
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
        self.goal_ids: list[uuid.UUID] = []

    def make_user(self, role: UserRole, name: str = "Test User") -> User:
        user = User(name=name, role=role)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user_ids.append(user.id)
        return user

    def connect(self, user: User, telegram_id: int) -> None:
        token = insert_activation(self.session, user.id)
        self.session.commit()
        activate_telegram_identity(self.session, token, telegram_id)

    def make_goal(
        self,
        creator: User,
        *,
        name: str = "Bicycle",
        cost_points: int = 100,
        accumulated_points: int = 0,
        status: GoalStatus = GoalStatus.ACTIVE,
    ) -> Goal:
        goal = Goal(
            name=name,
            cost_points=cost_points,
            accumulated_points=accumulated_points,
            status=status,
            created_by=creator.id,
        )
        self.session.add(goal)
        self.session.commit()
        self.session.refresh(goal)
        self.goal_ids.append(goal.id)
        return goal

    def make_contribution(
        self, goal: Goal, user: User, amount: int, *, created_at: datetime | None = None
    ) -> GoalContribution:
        contribution = GoalContribution(goal_id=goal.id, user_id=user.id, amount=amount)
        if created_at is not None:
            contribution.created_at = created_at
        self.session.add(contribution)
        self.session.commit()
        self.session.refresh(contribution)
        return contribution


@pytest.fixture
def real(db_session: Session) -> Iterator[RealData]:
    del db_session
    session = SessionLocal()
    data = RealData(session)
    try:
        yield data
    finally:
        session.rollback()
        if data.user_ids:
            session.query(PointTransaction).filter(
                PointTransaction.user_id.in_(data.user_ids)
            ).delete(synchronize_session=False)
        if data.goal_ids:
            session.query(GoalContribution).filter(
                GoalContribution.goal_id.in_(data.goal_ids)
            ).delete(synchronize_session=False)
            session.query(Goal).filter(Goal.id.in_(data.goal_ids)).delete(
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
# Goals list (Adult)
# =========================================================================================


def test_adult_can_open_the_full_goals_catalog(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.make_goal(adult, name="Bicycle", cost_points=500)
    real.make_goal(
        adult, name="Done goal", status=GoalStatus.COMPLETED, cost_points=10, accumulated_points=10
    )

    text, keyboard = _adult_goals_list_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Bicycle" in label for label in labels)
    assert any("Done goal" in label for label in labels)


def test_empty_goals_catalog_shows_the_no_goals_text(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _adult_goals_list_view(telegram_id)

    assert NO_GOALS_TEXT in text
    assert keyboard is not None


def test_child_cannot_open_the_adult_goals_catalog(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _adult_goals_list_view(telegram_id)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_goals_catalog_view_for_unconnected_account() -> None:
    text, keyboard = _adult_goals_list_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# `/goals` role dispatch
# =========================================================================================


def test_goals_command_shows_the_adult_management_view_for_an_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    real.make_goal(adult, name="Bicycle")

    text, keyboard = _goals_command_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Добавить цель" in label for label in labels)


def test_goals_command_shows_the_child_self_service_view_for_a_child(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.make_goal(adult, name="Bicycle", cost_points=250)

    text, keyboard = _goals_command_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Bicycle" in label for label in labels)
    assert not any("Добавить цель" in label for label in labels)


# =========================================================================================
# Goal details (Adult)
# =========================================================================================


def test_adult_goal_details_show_edit_button_when_active(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, status=GoalStatus.ACTIVE)

    _, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Изменить" in label for label in labels)


def test_adult_goal_details_hide_edit_button_when_completed(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    _, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any("Изменить" in label for label in labels)


def test_adult_goal_details_show_contribution_history(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, cost_points=500, accumulated_points=40)
    real.make_contribution(goal, child, 40)

    text, _ = _goal_details_view(telegram_id, str(goal.id), None)

    assert "Alex" in text
    assert "40" in text


def test_older_pagination_shows_the_next_page_of_contributions_for_adult(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, cost_points=1000)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(PAGE_SIZE + 1):
        real.make_contribution(goal, child, 1, created_at=base.replace(day=i + 1))

    first_text, first_keyboard = _goal_details_view(telegram_id, str(goal.id), None)
    assert first_keyboard is not None
    older_button = next(
        button
        for row in first_keyboard.inline_keyboard
        for button in row
        if button.text == "Ранее"
    )
    assert older_button.callback_data is not None
    payload = older_button.callback_data.removeprefix(OLDER_CALLBACK_PREFIX)
    goal_id, cursor = decode_older_payload(payload)
    assert goal_id == goal.id
    assert cursor is not None

    second_text, _ = _goal_details_view(telegram_id, str(goal_id), cursor)

    assert first_text != second_text


def test_goal_details_for_missing_goal_shows_not_found(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _goal_details_view(telegram_id, str(uuid.uuid4()), None)

    assert text == _GOAL_NOT_FOUND_TEXT
    assert keyboard is not None


def test_child_cannot_open_the_adult_goal_details_screen(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult)

    text, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


# =========================================================================================
# Create flow
# =========================================================================================


def test_starting_create_prompts_for_a_name(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is True
    assert text


def test_child_cannot_start_the_create_flow(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, should_start = _start_create(telegram_id)

    assert should_start is False
    assert text == _NOT_AN_ADULT_TEXT


def test_blank_name_is_rejected_and_flow_stays_open(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    flow = {"action": "create", "step": "name"}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "   ")

    assert finished is False
    assert flow["step"] == "name"


def test_valid_name_advances_to_the_cost_step(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    flow = {"action": "create", "step": "name"}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "Bicycle")

    assert finished is False
    assert flow["step"] == "cost"
    assert flow["name"] == "Bicycle"


def test_non_numeric_cost_is_rejected_during_create(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    flow = {"action": "create", "step": "cost", "name": "Bicycle"}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "not a number")

    assert finished is False


def test_successful_create_creates_an_active_goal(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    flow = {"action": "create", "step": "cost", "name": "Bicycle"}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "500")

    assert finished is True
    assert "Bicycle" in text
    created = real.session.query(Goal).filter_by(name="Bicycle", created_by=adult.id).one()
    real.goal_ids.append(created.id)
    assert created.cost_points == 500
    assert created.accumulated_points == 0
    assert created.status == GoalStatus.ACTIVE


def test_zero_cost_is_rejected_via_finish_create(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _finish_create(telegram_id, "Bicycle", 0)

    assert keyboard is None
    session = SessionLocal()
    try:
        count = session.query(Goal).filter_by(name="Bicycle", created_by=adult.id).count()
        assert count == 0
    finally:
        session.close()


# =========================================================================================
# Edit flow
# =========================================================================================


def test_starting_edit_menu_shows_current_name_and_cost(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, name="Bicycle", cost_points=500)

    text, keyboard = _start_edit_menu(telegram_id, str(goal.id))

    assert "Bicycle" in text
    assert "500" in text
    assert keyboard is not None


def test_starting_edit_menu_on_a_completed_goal_is_refused(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    text, keyboard = _start_edit_menu(telegram_id, str(goal.id))

    assert text == _GOAL_NOT_EDITABLE_TEXT
    assert keyboard is not None


def test_starting_edit_field_on_a_completed_goal_is_refused(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    text, keyboard, should_start = _start_edit_field(telegram_id, str(goal.id), "name")

    assert should_start is False
    assert text == _GOAL_NOT_EDITABLE_TEXT
    assert keyboard is not None


def test_child_cannot_start_editing_a_goal(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult)

    text, keyboard = _start_edit_menu(telegram_id, str(goal.id))

    assert text == _NOT_AN_ADULT_TEXT
    assert keyboard is None


def test_successful_edit_name_updates_the_goal(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, name="Old name", cost_points=500)

    text, keyboard = _finish_edit_name(telegram_id, str(goal.id), "New name")

    assert "New name" in text
    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.name == "New name"
    finally:
        session.close()


def test_successful_edit_cost_updates_the_goal(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, cost_points=500, accumulated_points=50)

    text, keyboard = _finish_edit_cost(telegram_id, str(goal.id), 800)

    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.cost_points == 800
        assert refreshed.status == GoalStatus.ACTIVE
    finally:
        session.close()


def test_reducing_cost_below_accumulated_points_completes_the_goal(real: RealData) -> None:
    """Issue: Goals worked example -- lowering cost_points to at or below
    the Goal's current accumulated_points must complete it immediately,
    exactly like reaching the target via a Child's contribution does.
    """
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, cost_points=500, accumulated_points=300)

    text, keyboard = _finish_edit_cost(telegram_id, str(goal.id), 300)

    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.cost_points == 300
        assert refreshed.status == GoalStatus.COMPLETED
    finally:
        session.close()


def test_reducing_cost_above_accumulated_points_leaves_the_goal_active(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, cost_points=500, accumulated_points=300)

    text, keyboard = _finish_edit_cost(telegram_id, str(goal.id), 350)

    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.status == GoalStatus.ACTIVE
    finally:
        session.close()


def test_editing_a_completed_goal_via_finish_edit_name_is_refused(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    text, keyboard = _finish_edit_name(telegram_id, str(goal.id), "New name")

    assert text == _GOAL_NOT_EDITABLE_TEXT
    assert keyboard is not None


def test_blank_name_is_rejected_during_edit(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)
    goal = real.make_goal(adult, name="Bicycle")

    text, keyboard = _finish_edit_name(telegram_id, str(goal.id), "   ")

    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.name == "Bicycle"
    finally:
        session.close()


def test_child_cannot_finish_editing_a_goal_even_with_a_crafted_call(real: RealData) -> None:
    """Defense in depth: even if a Child somehow reached _finish_edit_name
    directly, the Application layer's own authorization still refuses it.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult, name="Bicycle")

    text, _ = _finish_edit_name(telegram_id, str(goal.id), "Hacked")

    assert text == _NOT_AN_ADULT_TEXT
    session = SessionLocal()
    try:
        refreshed = session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.name == "Bicycle"
    finally:
        session.close()


# =========================================================================================
# Callback payload sanity
# =========================================================================================


def test_callback_prefixes_do_not_collide() -> None:
    sample_id = "12345678-1234-1234-1234-123456789012"
    prefixes = {
        "open": OPEN_CALLBACK_PREFIX,
        "older": OLDER_CALLBACK_PREFIX,
        "edit": EDIT_CALLBACK_PREFIX,
        "editname": EDIT_NAME_CALLBACK_PREFIX,
        "editcost": EDIT_COST_CALLBACK_PREFIX,
    }
    exact_matches = {
        "add": ADD_CALLBACK_DATA,
        "list": LIST_CALLBACK_DATA,
        "home": HOME_CALLBACK_DATA,
    }
    for name, prefix in prefixes.items():
        payload = f"{prefix}{sample_id}"
        for other_name, other_prefix in prefixes.items():
            if other_name == name:
                continue
            assert not payload.startswith(other_prefix), (
                f"{name} payload collides with {other_name}"
            )
        for other_name, exact in exact_matches.items():
            assert payload != exact, f"{name} payload collides with {other_name}"


def test_child_and_adult_goal_callback_prefixes_do_not_collide() -> None:
    """Issue: Goals -- the Child's goal:* prefixes and the Adult's
    adultgoal:* prefixes must never overlap, since bot.py registers
    CallbackQueryHandlers for both against the same Application.
    """
    from app.telegram.keyboards.goals import (
        OLDER_CALLBACK_PREFIX as CHILD_OLDER,
    )
    from app.telegram.keyboards.goals import (
        OPEN_CALLBACK_PREFIX as CHILD_OPEN,
    )

    assert not CHILD_OPEN.startswith(OPEN_CALLBACK_PREFIX)
    assert not OPEN_CALLBACK_PREFIX.startswith(CHILD_OPEN)
    assert not CHILD_OLDER.startswith(OLDER_CALLBACK_PREFIX)
    assert not OLDER_CALLBACK_PREFIX.startswith(CHILD_OLDER)
