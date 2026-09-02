import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    Task,
    TaskStatus,
    User,
    UserRole,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def make_task_completed_transaction(
    db_session: Session, user: User, amount: int, created_at: datetime | None = None
) -> PointTransaction:
    task = Task(
        title="Seed task",
        reward_points=amount,
        status=TaskStatus.COMPLETED,
        assigned_to=user.id,
        created_by=user.id,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    txn = PointTransaction(
        user_id=user.id,
        task_id=task.id,
        amount=amount,
        reason=PointTransactionReason.TASK_COMPLETED,
    )
    if created_at is not None:
        txn.created_at = created_at
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)
    return txn


def make_reward_redeemed_transaction(
    db_session: Session, user: User, amount: int, created_at: datetime | None = None
) -> PointTransaction:
    reward = Reward(name="Seed reward", cost_points=abs(amount), created_by=user.id)
    db_session.add(reward)
    db_session.commit()
    db_session.refresh(reward)

    redemption = RewardRedemption(reward_id=reward.id, user_id=user.id, cost_points=abs(amount))
    db_session.add(redemption)
    db_session.commit()
    db_session.refresh(redemption)

    txn = PointTransaction(
        user_id=user.id,
        redemption_id=redemption.id,
        amount=amount,
        reason=PointTransactionReason.REWARD_REDEEMED,
    )
    if created_at is not None:
        txn.created_at = created_at
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)
    return txn


# --- Balance --------------------------------------------------------------------------


def test_balance_is_zero_with_no_transactions(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/balance", headers=auth(adult))

    assert response.status_code == 200
    assert response.json() == {"balance": 0}


def test_positive_transaction_contributes_positively(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 100)

    response = client.get("/api/points/balance", headers=auth(adult))

    assert response.json() == {"balance": 100}


def test_negative_transaction_contributes_negatively(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 100)
    make_reward_redeemed_transaction(db_session, adult, -40)

    response = client.get("/api/points/balance", headers=auth(adult))

    assert response.json() == {"balance": 60}


def test_multiple_transactions_are_summed_correctly(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 50)
    make_task_completed_transaction(db_session, adult, 30)
    make_reward_redeemed_transaction(db_session, adult, -20)
    make_reward_redeemed_transaction(db_session, adult, -10)

    response = client.get("/api/points/balance", headers=auth(adult))

    assert response.json() == {"balance": 50}


def test_balance_only_reflects_the_current_users_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    user_a = make_user(ADULT, "User A")
    user_b = make_user(ADULT, "User B")
    make_task_completed_transaction(db_session, user_a, 100)
    make_task_completed_transaction(db_session, user_b, 999)

    response = client.get("/api/points/balance", headers=auth(user_a))

    assert response.json() == {"balance": 100}


def test_adult_can_read_balance(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/balance", headers=auth(adult))

    assert response.status_code == 200


def test_child_can_read_balance(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.get("/api/points/balance", headers=auth(child))

    assert response.status_code == 200


def test_balance_missing_identity_header_returns_401(client: TestClient) -> None:
    response = client.get("/api/points/balance")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_balance_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/balance", headers={"X-User-Id": str(adult.id)})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# --- History --------------------------------------------------------------------------


def test_user_receives_their_own_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 100)

    response = client.get("/api/points/history", headers=auth(adult))

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_history_excludes_another_users_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    user_a = make_user(ADULT, "User A")
    user_b = make_user(ADULT, "User B")
    make_task_completed_transaction(db_session, user_a, 100)
    make_task_completed_transaction(db_session, user_b, 200)
    make_reward_redeemed_transaction(db_session, user_b, -50)

    response = client.get("/api/points/history", headers=auth(user_a))

    body = response.json()
    assert len(body) == 1
    assert body[0]["amount"] == 100


def test_both_transaction_types_are_returned(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 100)
    make_reward_redeemed_transaction(db_session, adult, -30)

    response = client.get("/api/points/history", headers=auth(adult))

    reasons = {entry["reason"] for entry in response.json()}
    assert reasons == {"TASK_COMPLETED", "REWARD_REDEEMED"}


def test_task_id_is_returned_for_task_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    txn = make_task_completed_transaction(db_session, adult, 100)

    response = client.get("/api/points/history", headers=auth(adult))

    entry = response.json()[0]
    assert entry["task_id"] == str(txn.task_id)
    assert entry["redemption_id"] is None


def test_redemption_id_is_returned_for_redemption_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    make_task_completed_transaction(db_session, adult, 100)
    txn = make_reward_redeemed_transaction(db_session, adult, -30)

    response = client.get("/api/points/history", headers=auth(adult))

    entry = next(e for e in response.json() if e["reason"] == "REWARD_REDEEMED")
    assert entry["redemption_id"] == str(txn.redemption_id)
    assert entry["task_id"] is None


def test_history_sorted_by_created_at_descending(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    earliest = make_task_completed_transaction(
        db_session, adult, 10, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    middle = make_task_completed_transaction(
        db_session, adult, 20, created_at=datetime(2026, 1, 2, tzinfo=UTC)
    )
    latest = make_task_completed_transaction(
        db_session, adult, 30, created_at=datetime(2026, 1, 3, tzinfo=UTC)
    )

    response = client.get("/api/points/history", headers=auth(adult))

    ids = [entry["id"] for entry in response.json()]
    assert ids == [str(latest.id), str(middle.id), str(earliest.id)]


def test_identical_timestamps_use_id_descending_as_tiebreaker(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    same_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    first = make_task_completed_transaction(db_session, adult, 10, created_at=same_time)
    second = make_task_completed_transaction(db_session, adult, 20, created_at=same_time)
    expected_order = sorted([first.id, second.id], reverse=True)

    response = client.get("/api/points/history", headers=auth(adult))

    ids = [uuid.UUID(entry["id"]) for entry in response.json()]
    assert ids == expected_order


def test_empty_history_returns_200_empty_list(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/history", headers=auth(adult))

    assert response.status_code == 200
    assert response.json() == []


def test_adult_can_read_history(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/history", headers=auth(adult))

    assert response.status_code == 200


def test_child_can_read_history(client: TestClient, make_user: Callable[..., User]) -> None:
    child = make_user(CHILD)

    response = client.get("/api/points/history", headers=auth(child))

    assert response.status_code == 200


def test_history_missing_identity_header_returns_401(client: TestClient) -> None:
    response = client.get("/api/points/history")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_history_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)

    response = client.get("/api/points/history", headers={"X-User-Id": str(adult.id)})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


# --- Isolation --------------------------------------------------------------------------


def test_user_cannot_see_another_users_balance_via_their_own_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    user_a = make_user(ADULT, "User A")
    user_b = make_user(ADULT, "User B")
    make_task_completed_transaction(db_session, user_a, 40)
    make_task_completed_transaction(db_session, user_b, 999)
    make_reward_redeemed_transaction(db_session, user_b, -100)

    response_a = client.get("/api/points/balance", headers=auth(user_a))
    response_b = client.get("/api/points/balance", headers=auth(user_b))

    assert response_a.json() == {"balance": 40}
    assert response_b.json() == {"balance": 899}
