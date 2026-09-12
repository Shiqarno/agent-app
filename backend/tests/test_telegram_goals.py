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
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    TelegramIdentity,
    User,
    UserActivation,
    UserRole,
)
from app.telegram.handlers.goals import (
    _EXCEEDS_REMAINING_TEXT,
    _GOAL_ALREADY_COMPLETED_TEXT,
    _GOAL_NOT_FOUND_TEXT,
    _INSUFFICIENT_POINTS_TEXT,
    _INVALID_AMOUNT_TEXT,
    _NOT_A_CHILD_TEXT,
    _NOT_CONNECTED_TEXT,
    _finish_transfer,
    _goal_details_view,
    _goals_view,
    _route_flow_text,
    _start_transfer,
)
from app.telegram.keyboards.goals import (
    LIST_CALLBACK_DATA,
    OLDER_CALLBACK_PREFIX,
    OPEN_CALLBACK_PREFIX,
    TRANSFER_CALLBACK_PREFIX,
    TRANSFER_CONFIRM_CALLBACK_DATA,
    decode_older_payload,
)
from app.telegram.views.goals import NO_CONTRIBUTIONS_TEXT, NO_GOALS_TEXT
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
        self.task_ids: list[uuid.UUID] = []
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

    def seed_balance(self, user: User, amount: int, *, title: str = "Seed task") -> None:
        task = Task(title=title, reward_points=amount, created_by=user.id)
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task_ids.append(task.id)

        execution = TaskExecution(
            task_id=task.id,
            user_id=user.id,
            status=TaskExecutionStatus.COMPLETED,
            reward_points=amount,
        )
        self.session.add(execution)
        self.session.commit()
        self.session.refresh(execution)

        self.session.add(
            PointTransaction(
                user_id=user.id,
                task_execution_id=execution.id,
                amount=amount,
                reason=PointTransactionReason.TASK_COMPLETED,
            )
        )
        self.session.commit()

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

        self.session.add(
            PointTransaction(
                user_id=user.id,
                goal_contribution_id=contribution.id,
                amount=-amount,
                reason=PointTransactionReason.GOAL_CONTRIBUTION,
            )
        )
        self.session.commit()
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
        if data.task_ids:
            session.query(TaskExecution).filter(TaskExecution.task_id.in_(data.task_ids)).delete(
                synchronize_session=False
            )
            session.query(Task).filter(Task.id.in_(data.task_ids)).delete(synchronize_session=False)
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
# Goals list
# =========================================================================================


def test_child_can_open_the_goals_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.make_goal(adult, name="Bicycle", cost_points=500)

    text, keyboard = _goals_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Bicycle" in label and "500" in label for label in labels)


def test_empty_goals_list_shows_the_no_goals_text(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _goals_view(telegram_id)

    assert NO_GOALS_TEXT in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 0


def test_completed_goal_is_not_shown_in_the_child_list(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.make_goal(adult, name="Done goal", status=GoalStatus.COMPLETED, accumulated_points=100)

    text, keyboard = _goals_view(telegram_id)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any("Done goal" in label for label in labels)


def test_adult_does_not_get_the_child_goals_ux(real: RealData) -> None:
    adult = real.make_user(ADULT)
    telegram_id = _next_telegram_id()
    real.connect(adult, telegram_id)

    text, keyboard = _goals_view(telegram_id)

    assert text == _NOT_A_CHILD_TEXT
    assert keyboard is None


def test_goals_view_for_unconnected_account() -> None:
    text, keyboard = _goals_view(_next_telegram_id())

    assert text == _NOT_CONNECTED_TEXT
    assert keyboard is None


# =========================================================================================
# Goal details
# =========================================================================================


def test_goal_details_show_cost_accumulated_and_history(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult, name="Bicycle", cost_points=500, accumulated_points=100)
    real.make_contribution(goal, child, 100)

    text, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert "Bicycle" in text
    assert "500" in text
    assert "100" in text
    assert "Alex" in text
    assert keyboard is not None


def test_goal_details_with_no_contributions_shows_the_empty_history_text(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult)

    text, _ = _goal_details_view(telegram_id, str(goal.id), None)

    assert NO_CONTRIBUTIONS_TEXT in text


def test_active_goal_shows_the_transfer_button(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult, status=GoalStatus.ACTIVE)

    _, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Перевести баллы" in label for label in labels)


def test_completed_goal_does_not_show_the_transfer_button(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    text, keyboard = _goal_details_view(telegram_id, str(goal.id), None)

    assert "✓" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert not any("Перевести баллы" in label for label in labels)


def test_goal_details_for_missing_goal_shows_not_found(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, keyboard = _goal_details_view(telegram_id, str(uuid.uuid4()), None)

    assert text == _GOAL_NOT_FOUND_TEXT
    assert keyboard is not None


def test_older_pagination_shows_the_next_page_of_contributions(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD, "Alex")
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
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


def test_decode_older_payload_rejects_malformed_input() -> None:
    goal_id, cursor = decode_older_payload("garbage")

    assert goal_id is None
    assert cursor is None


# =========================================================================================
# Transfer flow: starting
# =========================================================================================


def test_starting_transfer_prompts_for_an_amount(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 50)
    goal = real.make_goal(adult, cost_points=500)

    text, should_start, keyboard = _start_transfer(telegram_id, str(goal.id))

    assert should_start is True
    assert keyboard is None
    assert "50" in text


def test_starting_transfer_on_a_completed_goal_is_refused(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(
        adult, status=GoalStatus.COMPLETED, cost_points=100, accumulated_points=100
    )

    text, should_start, keyboard = _start_transfer(telegram_id, str(goal.id))

    assert should_start is False
    assert text == _GOAL_ALREADY_COMPLETED_TEXT
    assert keyboard is not None


def test_starting_transfer_on_a_missing_goal_is_refused(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)

    text, should_start, _ = _start_transfer(telegram_id, str(uuid.uuid4()))

    assert should_start is False
    assert text == _GOAL_NOT_FOUND_TEXT


# =========================================================================================
# Transfer flow: entering the amount
# =========================================================================================


def test_non_numeric_amount_is_rejected_and_flow_stays_open(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult, cost_points=500)
    flow = {"goal_id": str(goal.id)}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "not a number")

    assert finished is False
    assert keyboard is None
    assert text == _INVALID_AMOUNT_TEXT


def test_zero_or_negative_amount_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    goal = real.make_goal(adult, cost_points=500)
    flow = {"goal_id": str(goal.id)}

    text, _, finished = _route_flow_text(telegram_id, flow, "0")

    assert finished is False
    assert text == _INVALID_AMOUNT_TEXT


def test_amount_exceeding_the_remaining_target_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 1000)
    goal = real.make_goal(adult, cost_points=100, accumulated_points=90)
    flow = {"goal_id": str(goal.id)}

    text, _, finished = _route_flow_text(telegram_id, flow, "50")

    assert finished is False
    assert text == _EXCEEDS_REMAINING_TEXT


def test_amount_exceeding_available_balance_is_rejected(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 10)
    goal = real.make_goal(adult, cost_points=500)
    flow = {"goal_id": str(goal.id)}

    text, _, finished = _route_flow_text(telegram_id, flow, "20")

    assert finished is False
    assert text == _INSUFFICIENT_POINTS_TEXT


def test_valid_amount_shows_the_transfer_confirmation(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 100)
    goal = real.make_goal(adult, name="Bicycle", cost_points=500)
    flow = {"goal_id": str(goal.id)}

    text, keyboard, finished = _route_flow_text(telegram_id, flow, "40")

    assert finished is False
    assert flow["amount"] == 40
    assert "Bicycle" in text
    assert "40" in text
    assert "60" in text
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert any("Перевести" in label for label in labels)


def test_invalid_amount_does_not_create_a_contribution(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 10)
    goal = real.make_goal(adult, cost_points=500)
    flow = {"goal_id": str(goal.id)}

    _route_flow_text(telegram_id, flow, "1000")

    session = SessionLocal()
    try:
        count = session.query(GoalContribution).filter_by(goal_id=goal.id).count()
        assert count == 0
        refreshed_goal = session.get(Goal, goal.id)
        assert refreshed_goal is not None
        assert refreshed_goal.accumulated_points == 0
    finally:
        session.close()


# =========================================================================================
# Transfer flow: confirming
# =========================================================================================


def test_confirming_the_transfer_updates_goal_and_balance(real: RealData) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 100)
    goal = real.make_goal(adult, name="Bicycle", cost_points=500)
    flow = {"goal_id": str(goal.id), "amount": 40}

    text, keyboard = _finish_transfer(telegram_id, flow)

    assert "40" in text
    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed_goal = session.get(Goal, goal.id)
        assert refreshed_goal is not None
        assert refreshed_goal.accumulated_points == 40
        assert refreshed_goal.status == GoalStatus.ACTIVE
        contribution_count = session.query(GoalContribution).filter_by(goal_id=goal.id).count()
        assert contribution_count == 1
    finally:
        session.close()


def test_confirming_a_transfer_that_reaches_the_target_completes_the_goal(
    real: RealData,
) -> None:
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 100)
    goal = real.make_goal(adult, name="Bicycle", cost_points=100, accumulated_points=90)
    flow = {"goal_id": str(goal.id), "amount": 10}

    text, keyboard = _finish_transfer(telegram_id, flow)

    assert keyboard is not None
    session = SessionLocal()
    try:
        refreshed_goal = session.get(Goal, goal.id)
        assert refreshed_goal is not None
        assert refreshed_goal.accumulated_points == 100
        assert refreshed_goal.status == GoalStatus.COMPLETED
    finally:
        session.close()


def test_confirming_transfer_with_a_now_completed_goal_is_refused(real: RealData) -> None:
    """The confirmation was shown when the Goal was still ACTIVE, but it was
    completed by someone else before the Child tapped confirm.
    """
    adult = real.make_user(ADULT)
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    real.seed_balance(child, 100)
    goal = real.make_goal(
        adult, name="Bicycle", cost_points=100, accumulated_points=100, status=GoalStatus.COMPLETED
    )
    flow = {"goal_id": str(goal.id), "amount": 10}

    text, keyboard = _finish_transfer(telegram_id, flow)

    assert text == _GOAL_ALREADY_COMPLETED_TEXT
    assert keyboard is not None
    session = SessionLocal()
    try:
        contribution_count = session.query(GoalContribution).filter_by(goal_id=goal.id).count()
        assert contribution_count == 0
    finally:
        session.close()


def test_confirming_transfer_for_a_missing_goal_is_refused(real: RealData) -> None:
    child = real.make_user(CHILD)
    telegram_id = _next_telegram_id()
    real.connect(child, telegram_id)
    flow = {"goal_id": str(uuid.uuid4()), "amount": 10}

    text, keyboard = _finish_transfer(telegram_id, flow)

    assert text == _GOAL_NOT_FOUND_TEXT
    assert keyboard is not None


# =========================================================================================
# Callback payload sanity
# =========================================================================================


def test_callback_prefixes_do_not_collide() -> None:
    sample_id = "12345678-1234-1234-1234-123456789012"
    prefixes = {
        "open": OPEN_CALLBACK_PREFIX,
        "older": OLDER_CALLBACK_PREFIX,
        "transfer": TRANSFER_CALLBACK_PREFIX,
    }
    exact_matches = {"list": LIST_CALLBACK_DATA, "transferconfirm": TRANSFER_CONFIRM_CALLBACK_DATA}
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


def test_open_callback_data_fits_within_telegrams_64_byte_limit(real: RealData) -> None:
    adult = real.make_user(ADULT)
    goal = real.make_goal(adult, cost_points=500)

    callback_data = f"{OPEN_CALLBACK_PREFIX}{goal.id}"

    assert len(callback_data.encode("utf-8")) <= 64
