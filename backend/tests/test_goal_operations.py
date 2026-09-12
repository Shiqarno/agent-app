import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.goal_operations import (
    ContributionExceedsRemainingAmountError,
    GoalNotActiveError,
    GoalNotEditableError,
    GoalNotFoundError,
    InsufficientPointsError,
    InvalidContributionAmountError,
    InvalidGoalInputError,
    NotAChildError,
    NotAnAdultError,
    contribute_to_goal,
    create_goal,
    get_active_goals,
    get_goal_details,
    get_goals,
    update_goal,
)
from app.models import (
    Goal,
    GoalContribution,
    GoalStatus,
    PointTransaction,
    PointTransactionReason,
    Task,
    TaskExecution,
    TaskExecutionStatus,
    User,
    UserRole,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _make_goal(
    db_session: Session,
    creator: User,
    *,
    name: str = "Поездка в зоопарк",
    cost_points: int = 50,
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
    db_session.add(goal)
    db_session.commit()
    db_session.refresh(goal)
    return goal


def _grant_points(db_session: Session, user: User, amount: int) -> None:
    task = Task(title="Balance seed", reward_points=amount, created_by=user.id)
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    execution = TaskExecution(
        task_id=task.id,
        user_id=user.id,
        status=TaskExecutionStatus.COMPLETED,
        reward_points=amount,
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)

    db_session.add(
        PointTransaction(
            user_id=user.id,
            task_execution_id=execution.id,
            amount=amount,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    db_session.commit()


# =========================================================================================
# Goal creation
# =========================================================================================


def test_adult_can_create_a_goal(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    goal = create_goal(db_session, adult, name="Новый велосипед", cost_points=200)

    assert goal.name == "Новый велосипед"
    assert goal.cost_points == 200
    assert goal.accumulated_points == 0
    assert goal.status == GoalStatus.ACTIVE
    assert goal.created_by == adult.id


def test_child_cannot_create_a_goal(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)

    with pytest.raises(NotAnAdultError):
        create_goal(db_session, child, name="Новый велосипед", cost_points=200)


def test_zero_cost_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    with pytest.raises(InvalidGoalInputError):
        create_goal(db_session, adult, name="Новый велосипед", cost_points=0)


def test_negative_cost_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    with pytest.raises(InvalidGoalInputError):
        create_goal(db_session, adult, name="Новый велосипед", cost_points=-10)


def test_blank_name_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    with pytest.raises(InvalidGoalInputError):
        create_goal(db_session, adult, name="   ", cost_points=50)


# =========================================================================================
# Goal editing
# =========================================================================================


def test_adult_can_edit_an_active_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    goal = _make_goal(db_session, adult, name="Old name", cost_points=50)

    updated = update_goal(db_session, adult, goal.id, name="New name", cost_points=60)

    assert updated.name == "New name"
    assert updated.cost_points == 60
    assert updated.status == GoalStatus.ACTIVE


def test_child_cannot_edit_a_goal(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    goal = _make_goal(db_session, adult)

    with pytest.raises(NotAnAdultError):
        update_goal(db_session, child, goal.id, name="Hacked")


def test_completed_goal_cannot_be_edited(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    goal = _make_goal(
        db_session, adult, cost_points=50, accumulated_points=50, status=GoalStatus.COMPLETED
    )

    with pytest.raises(GoalNotEditableError):
        update_goal(db_session, adult, goal.id, name="New name")

    db_session.refresh(goal)
    assert goal.name != "New name"
    assert goal.status == GoalStatus.COMPLETED


def test_reducing_cost_to_the_accumulated_amount_completes_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    goal = _make_goal(db_session, adult, cost_points=100, accumulated_points=80)

    updated = update_goal(db_session, adult, goal.id, cost_points=80)

    assert updated.cost_points == 80
    assert updated.accumulated_points == 80
    assert updated.status == GoalStatus.COMPLETED


def test_reducing_cost_below_the_accumulated_amount_completes_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    goal = _make_goal(db_session, adult, cost_points=100, accumulated_points=80)

    updated = update_goal(db_session, adult, goal.id, cost_points=50)

    assert updated.cost_points == 50
    assert updated.status == GoalStatus.COMPLETED


def test_active_goal_remains_active_when_accumulated_amount_is_below_new_cost(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    goal = _make_goal(db_session, adult, cost_points=100, accumulated_points=30)

    updated = update_goal(db_session, adult, goal.id, cost_points=150)

    assert updated.status == GoalStatus.ACTIVE


def test_editing_a_nonexistent_goal_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    with pytest.raises(GoalNotFoundError):
        update_goal(db_session, adult, uuid.uuid4(), name="New name")


# =========================================================================================
# Listing
# =========================================================================================


def test_get_active_goals_excludes_completed_goals(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    active = _make_goal(db_session, adult, name="Active goal")
    _make_goal(db_session, adult, name="Completed goal", status=GoalStatus.COMPLETED)

    goals = get_active_goals(db_session, child)

    assert [g.id for g in goals] == [active.id]


def test_get_active_goals_rejects_an_adult(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    with pytest.raises(NotAChildError):
        get_active_goals(db_session, adult)


def test_get_goals_includes_active_and_completed(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    active = _make_goal(db_session, adult, name="Active goal")
    completed = _make_goal(db_session, adult, name="Completed goal", status=GoalStatus.COMPLETED)

    goals = get_goals(db_session, adult)

    assert {g.id for g in goals} == {active.id, completed.id}


def test_get_goals_rejects_a_child(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)

    with pytest.raises(NotAnAdultError):
        get_goals(db_session, child)


# =========================================================================================
# Goal transfer -- happy paths
# =========================================================================================


def test_child_can_transfer_points_to_an_active_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50, accumulated_points=0)

    contribution, updated_goal, new_balance = contribute_to_goal(db_session, child, goal.id, 20)

    assert contribution.amount == 20
    assert contribution.goal_id == goal.id
    assert contribution.user_id == child.id
    assert updated_goal.accumulated_points == 20
    assert updated_goal.status == GoalStatus.ACTIVE
    assert new_balance == 80


def test_transfer_creates_a_goal_contribution_point_transaction(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    contribution, _goal, _balance = contribute_to_goal(db_session, child, goal.id, 20)

    transaction = db_session.scalars(
        select(PointTransaction).where(PointTransaction.goal_contribution_id == contribution.id)
    ).one()
    assert transaction.amount == -20
    assert transaction.reason == PointTransactionReason.GOAL_CONTRIBUTION
    assert transaction.user_id == child.id


def test_transfer_creates_a_contribution_record(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    contribute_to_goal(db_session, child, goal.id, 20)

    count = db_session.scalar(
        select(func.count())
        .select_from(GoalContribution)
        .where(GoalContribution.goal_id == goal.id, GoalContribution.user_id == child.id)
    )
    assert count == 1


def test_transfer_deducts_from_the_childs_ledger_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    from app.reward_operations import get_balance

    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    contribute_to_goal(db_session, child, goal.id, 20)

    assert get_balance(db_session, child.id) == 80


def test_successful_transfer_reaching_target_completes_the_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50, accumulated_points=30)

    _contribution, updated_goal, _balance = contribute_to_goal(db_session, child, goal.id, 20)

    assert updated_goal.accumulated_points == 50
    assert updated_goal.status == GoalStatus.COMPLETED


def test_successful_transfer_below_target_keeps_goal_active(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50, accumulated_points=30)

    _contribution, updated_goal, _balance = contribute_to_goal(db_session, child, goal.id, 10)

    assert updated_goal.accumulated_points == 40
    assert updated_goal.status == GoalStatus.ACTIVE


# =========================================================================================
# Goal transfer -- rejections
# =========================================================================================


def test_child_cannot_contribute_another_users_points(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    with pytest.raises(NotAChildError):
        contribute_to_goal(db_session, adult, uuid.uuid4(), 10)


def test_transfer_cannot_exceed_available_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 10)
    goal = _make_goal(db_session, adult, cost_points=50)

    with pytest.raises(InsufficientPointsError):
        contribute_to_goal(db_session, child, goal.id, 20)

    db_session.refresh(goal)
    assert goal.accumulated_points == 0


def test_transfer_respects_available_balance_not_raw_ledger_balance(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """A pending Reward request already has its cost frozen against the
    Child's balance (Issue #39) -- a Goal transfer must not be allowed to
    spend those same points.
    """
    from app.models import Reward
    from app.reward_operations import request_reward_redemption

    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 50)
    reward = Reward(name="Ice cream", cost_points=40, created_by=adult.id)
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)
    request_reward_redemption(db_session, child, reward.id)  # freezes 40, leaving 10 available

    goal = _make_goal(db_session, adult, cost_points=50)

    with pytest.raises(InsufficientPointsError):
        contribute_to_goal(db_session, child, goal.id, 20)


def test_transfer_cannot_exceed_remaining_goal_amount(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50, accumulated_points=30)

    with pytest.raises(ContributionExceedsRemainingAmountError):
        contribute_to_goal(db_session, child, goal.id, 25)

    db_session.refresh(goal)
    assert goal.accumulated_points == 30


def test_zero_transfer_is_rejected(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    with pytest.raises(InvalidContributionAmountError):
        contribute_to_goal(db_session, child, goal.id, 0)


def test_negative_transfer_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    with pytest.raises(InvalidContributionAmountError):
        contribute_to_goal(db_session, child, goal.id, -10)


def test_transfer_to_a_completed_goal_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(
        db_session, adult, cost_points=50, accumulated_points=50, status=GoalStatus.COMPLETED
    )

    with pytest.raises(GoalNotActiveError):
        contribute_to_goal(db_session, child, goal.id, 10)


def test_transfer_to_a_nonexistent_goal_is_rejected(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)

    with pytest.raises(GoalNotFoundError):
        contribute_to_goal(db_session, child, uuid.uuid4(), 10)


def test_failed_transfer_creates_no_partial_state(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 10)
    goal = _make_goal(db_session, adult, cost_points=50)

    with pytest.raises(InsufficientPointsError):
        contribute_to_goal(db_session, child, goal.id, 20)

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(GoalContribution)
            .where(GoalContribution.goal_id == goal.id)
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PointTransaction)
            .where(
                PointTransaction.user_id == child.id,
                PointTransaction.reason == PointTransactionReason.GOAL_CONTRIBUTION,
            )
        )
        == 0
    )


# =========================================================================================
# Multiple Children
# =========================================================================================


def test_multiple_children_can_contribute_to_the_same_goal(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    _grant_points(db_session, child_a, 100)
    _grant_points(db_session, child_b, 100)
    goal = _make_goal(db_session, adult, cost_points=100)

    contribute_to_goal(db_session, child_a, goal.id, 30)
    contribute_to_goal(db_session, child_b, goal.id, 40)
    _contribution, updated_goal, _balance = contribute_to_goal(db_session, child_a, goal.id, 30)

    assert updated_goal.accumulated_points == 100
    assert updated_goal.status == GoalStatus.COMPLETED


def test_contribution_history_identifies_the_contributing_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    _grant_points(db_session, child_a, 100)
    _grant_points(db_session, child_b, 100)
    goal = _make_goal(db_session, adult, cost_points=100)

    contribute_to_goal(db_session, child_a, goal.id, 30)
    contribute_to_goal(db_session, child_b, goal.id, 40)

    view = get_goal_details(db_session, goal.id)

    names = {item.child_name for item in view.contributions}
    assert names == {"Child A", "Child B"}


def test_goal_completes_based_on_total_accumulated_points_regardless_of_contributor(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    _grant_points(db_session, child_a, 100)
    _grant_points(db_session, child_b, 100)
    goal = _make_goal(db_session, adult, cost_points=50)

    contribute_to_goal(db_session, child_a, goal.id, 25)
    _contribution, updated_goal, _balance = contribute_to_goal(db_session, child_b, goal.id, 25)

    assert updated_goal.status == GoalStatus.COMPLETED


# =========================================================================================
# History / pagination
# =========================================================================================


def test_get_goal_details_raises_for_a_nonexistent_goal(
    db_session: Session,
) -> None:
    with pytest.raises(GoalNotFoundError):
        get_goal_details(db_session, uuid.uuid4())


def test_contributions_are_returned_newest_first(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=100)

    contribute_to_goal(db_session, child, goal.id, 10)
    contribute_to_goal(db_session, child, goal.id, 20)
    contribute_to_goal(db_session, child, goal.id, 30)

    view = get_goal_details(db_session, goal.id)

    assert [item.amount for item in view.contributions] == [30, 20, 10]


def test_completed_goal_retains_its_history(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=20)

    contribute_to_goal(db_session, child, goal.id, 20)

    view = get_goal_details(db_session, goal.id)

    assert view.goal.status == GoalStatus.COMPLETED
    assert [item.amount for item in view.contributions] == [20]


def test_goal_details_pagination_returns_a_next_cursor_when_more_remain(
    make_user: Callable[..., User], db_session: Session
) -> None:
    from app.goal_operations import PAGE_SIZE

    adult = make_user(ADULT)
    child = make_user(CHILD)
    _grant_points(db_session, child, 100)
    goal = _make_goal(db_session, adult, cost_points=100)
    for _ in range(PAGE_SIZE + 1):
        contribute_to_goal(db_session, child, goal.id, 1)

    first_page = get_goal_details(db_session, goal.id)
    assert len(first_page.contributions) == PAGE_SIZE
    assert first_page.next_cursor is not None

    second_page = get_goal_details(db_session, goal.id, cursor=first_page.next_cursor)
    assert len(second_page.contributions) == 1


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_transfers_competing_for_the_final_remaining_amount() -> None:
    """Goal cost=50, accumulated=40. Two different Children each attempt a
    10-point transfer at the same time -- exactly one must succeed (taking
    the Goal to COMPLETED at exactly 50), the other must be rejected. The
    Goal must never exceed its nominal cost.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child_a = User(name="Concurrent Child A", role=CHILD)
    child_b = User(name="Concurrent Child B", role=CHILD)
    setup_session.add_all([adult, child_a, child_b])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child_a)
    setup_session.refresh(child_b)

    _grant_points(setup_session, child_a, 100)
    _grant_points(setup_session, child_b, 100)

    goal = Goal(
        name="Race goal",
        cost_points=50,
        accumulated_points=40,
        status=GoalStatus.ACTIVE,
        created_by=adult.id,
    )
    setup_session.add(goal)
    setup_session.commit()
    setup_session.refresh(goal)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(child_id: uuid.UUID) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                child = session.get(User, child_id)
                assert child is not None
                contribute_to_goal(session, child, goal.id, 10)
                results.append("success")
            except (
                ContributionExceedsRemainingAmountError,
                GoalNotActiveError,
            ):
                results.append("rejected")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(child_a.id,)),
            threading.Thread(target=attempt, args=(child_b.id,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["rejected", "success"]

        setup_session.expire_all()
        refreshed = setup_session.get(Goal, goal.id)
        assert refreshed is not None
        assert refreshed.accumulated_points == 50
        assert refreshed.status == GoalStatus.COMPLETED

        contribution_count = setup_session.scalar(
            select(func.count())
            .select_from(GoalContribution)
            .where(GoalContribution.goal_id == goal.id)
        )
        assert contribution_count == 1
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter(
            PointTransaction.user_id.in_([child_a.id, child_b.id])
        ).delete(synchronize_session=False)
        setup_session.query(GoalContribution).filter_by(goal_id=goal.id).delete(
            synchronize_session=False
        )
        setup_session.query(Goal).filter_by(id=goal.id).delete(synchronize_session=False)
        setup_session.query(TaskExecution).filter(
            TaskExecution.user_id.in_([child_a.id, child_b.id])
        ).delete(synchronize_session=False)
        setup_session.query(Task).filter(
            Task.created_by.in_([child_a.id, child_b.id])
        ).delete(synchronize_session=False)
        setup_session.query(User).filter(
            User.id.in_([adult.id, child_a.id, child_b.id])
        ).delete(synchronize_session=False)
        setup_session.commit()
        setup_session.close()


def test_concurrent_transfers_by_the_same_child_cannot_double_spend() -> None:
    """A single Child with 100 available points attempts two concurrent
    60-point transfers to two different Goals -- only one can possibly
    succeed; the Child must never end up having spent 120 points.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=ADULT)
    child = User(name="Concurrent Child", role=CHILD)
    setup_session.add_all([adult, child])
    setup_session.commit()
    setup_session.refresh(adult)
    setup_session.refresh(child)

    _grant_points(setup_session, child, 100)

    goal_a = Goal(name="Goal A", cost_points=1000, accumulated_points=0, created_by=adult.id)
    goal_b = Goal(name="Goal B", cost_points=1000, accumulated_points=0, created_by=adult.id)
    setup_session.add_all([goal_a, goal_b])
    setup_session.commit()
    setup_session.refresh(goal_a)
    setup_session.refresh(goal_b)

    try:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(goal_id: uuid.UUID) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                acting_child = session.get(User, child.id)
                assert acting_child is not None
                contribute_to_goal(session, acting_child, goal_id, 60)
                results.append("success")
            except InsufficientPointsError:
                results.append("rejected")
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(goal_a.id,)),
            threading.Thread(target=attempt, args=(goal_b.id,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["rejected", "success"]

        from app.reward_operations import get_balance

        setup_session.expire_all()
        assert get_balance(setup_session, child.id) == 40
    finally:
        setup_session.rollback()
        setup_session.query(PointTransaction).filter_by(user_id=child.id).delete(
            synchronize_session=False
        )
        setup_session.query(GoalContribution).filter_by(user_id=child.id).delete(
            synchronize_session=False
        )
        setup_session.query(Goal).filter(Goal.id.in_([goal_a.id, goal_b.id])).delete(
            synchronize_session=False
        )
        setup_session.query(TaskExecution).filter_by(user_id=child.id).delete(
            synchronize_session=False
        )
        setup_session.query(Task).filter_by(created_by=child.id).delete(
            synchronize_session=False
        )
        setup_session.query(User).filter(User.id.in_([adult.id, child.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
