import hashlib
import secrets
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.db import SessionLocal
from app.identity import SESSION_COOKIE_NAME
from app.main import app
from app.models import (
    PointTransaction,
    PointTransactionReason,
    Reward,
    RewardRedemption,
    Task,
    TaskStatus,
    User,
    UserRole,
    UserSession,
    utcnow,
)


def real_session_headers(session: Session, user_id: uuid.UUID) -> dict[str, str]:
    """Like conftest.auth(), but against an explicitly supplied, real,
    independently-committing session -- for tests (e.g. the concurrency test
    below) that intentionally bypass the shared savepoint-isolated
    db_session fixture.
    """
    raw_token = secrets.token_urlsafe(32)
    csrf_value = secrets.token_urlsafe(16)
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=utcnow() + timedelta(days=7),
        )
    )
    session.commit()
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={raw_token}; {CSRF_COOKIE_NAME}={csrf_value}",
        CSRF_HEADER_NAME: csrf_value,
    }

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def create_reward(client: TestClient, adult: User, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"name": "Redeemable reward", "cost_points": 50}
    payload.update(overrides)
    response = client.post("/api/rewards", json=payload, headers=auth(adult))
    return response.json()


def seed_balance(db_session: Session, user: User, amount: int) -> None:
    """Give `user` `amount` points via a real completed Task, mirroring how
    balance is actually earned in this application (Issue #3)."""
    task = Task(
        title="Balance seed",
        reward_points=amount,
        status=TaskStatus.COMPLETED,
        assigned_to=user.id,
        created_by=user.id,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    db_session.add(
        PointTransaction(
            user_id=user.id,
            task_id=task.id,
            amount=amount,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    db_session.commit()


def balance_of(db_session: Session, user_id: uuid.UUID) -> int:
    result = db_session.scalar(
        select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
            PointTransaction.user_id == user_id
        )
    )
    assert result is not None
    return result


# --- Basic redemption -----------------------------------------------------------------


def test_adult_can_redeem_a_reward(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 201
    body = response.json()
    assert body["reward_id"] == reward["id"]
    assert body["user_id"] == str(adult.id)
    assert body["cost_points"] == 50


def test_child_can_redeem_a_reward(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    seed_balance(db_session, child, 100)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(child))

    assert response.status_code == 201
    assert response.json()["user_id"] == str(child.id)


def test_reward_creator_can_redeem_their_own_reward(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 201


def test_a_different_adult_can_redeem_the_reward(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    creator = make_user(ADULT, "Creator")
    other_adult = make_user(ADULT, "Other Adult")
    seed_balance(db_session, other_adult, 100)
    reward = create_reward(client, creator, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(other_adult))

    assert response.status_code == 201


def test_user_can_redeem_the_same_reward_multiple_times(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 150)
    reward = create_reward(client, adult, cost_points=50)

    first = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))
    second = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))
    third = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert [first.status_code, second.status_code, third.status_code] == [201, 201, 201]
    assert len({first.json()["id"], second.json()["id"], third.json()["id"]}) == 3


# --- Price snapshot ---------------------------------------------------------------------


def test_redemption_stores_the_current_reward_price(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    reward = create_reward(client, adult, cost_points=75)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.json()["cost_points"] == 75


def test_changing_reward_price_after_redemption_does_not_change_the_snapshot(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 200)
    reward = create_reward(client, adult, cost_points=100)

    redemption = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult)).json()

    client.patch(f"/api/rewards/{reward['id']}", json={"cost_points": 150}, headers=auth(adult))

    stored = db_session.get(RewardRedemption, uuid.UUID(redemption["id"]))
    assert stored is not None
    assert stored.cost_points == 100


def test_point_transaction_amount_equals_negative_snapshot_price(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 200)
    reward = create_reward(client, adult, cost_points=100)

    redemption = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult)).json()
    client.patch(f"/api/rewards/{reward['id']}", json={"cost_points": 150}, headers=auth(adult))

    txn = db_session.scalar(
        select(PointTransaction).where(
            PointTransaction.redemption_id == uuid.UUID(redemption["id"])
        )
    )
    assert txn is not None
    assert txn.amount == -100


# --- Balance ------------------------------------------------------------------------------


def test_redemption_succeeds_when_balance_equals_cost_exactly(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 50)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 201
    assert balance_of(db_session, adult.id) == 0


def test_redemption_succeeds_when_balance_exceeds_cost(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 200)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 201
    assert balance_of(db_session, adult.id) == 150


def test_redemption_fails_when_balance_is_less_than_cost(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 49)
    reward = create_reward(client, adult, cost_points=50)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_POINTS"


def test_insufficient_balance_creates_no_redemption(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 10)
    reward = create_reward(client, adult, cost_points=50)

    client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    count = db_session.scalar(
        select(func.count())
        .select_from(RewardRedemption)
        .where(RewardRedemption.user_id == adult.id)
    )
    assert count == 0


def test_insufficient_balance_creates_no_point_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 10)
    reward = create_reward(client, adult, cost_points=50)

    client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    txn_count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED)
    )
    assert txn_count == 0


def test_zero_balance_user_cannot_redeem_a_positive_cost_reward(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult, cost_points=1)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_POINTS"


# --- Ledger ---------------------------------------------------------------------------------


def test_successful_redemption_creates_exactly_one_negative_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    reward = create_reward(client, adult, cost_points=50)

    redemption = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult)).json()

    txns = list(
        db_session.scalars(
            select(PointTransaction).where(
                PointTransaction.redemption_id == uuid.UUID(redemption["id"])
            )
        )
    )
    assert len(txns) == 1
    assert txns[0].amount == -50
    assert txns[0].reason == PointTransactionReason.REWARD_REDEEMED


def test_transaction_belongs_to_the_current_user(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD)
    seed_balance(db_session, child, 100)
    reward = create_reward(client, adult, cost_points=50)

    redemption = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(child)).json()

    txn = db_session.scalar(
        select(PointTransaction).where(
            PointTransaction.redemption_id == uuid.UUID(redemption["id"])
        )
    )
    assert txn is not None
    assert txn.user_id == child.id


def test_existing_task_completed_transactions_remain_unchanged(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    task_txn = db_session.scalar(
        select(PointTransaction).where(PointTransaction.user_id == adult.id)
    )
    assert task_txn is not None
    original_amount, original_reason = task_txn.amount, task_txn.reason

    reward = create_reward(client, adult, cost_points=50)
    client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    db_session.refresh(task_txn)
    assert task_txn.amount == original_amount
    assert task_txn.reason == original_reason


def test_multiple_redemptions_create_separate_transactions(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 200)
    reward = create_reward(client, adult, cost_points=50)

    client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))
    client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    txn_count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == adult.id,
            PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
        )
    )
    assert txn_count == 2


# --- Atomicity --------------------------------------------------------------------------------


def test_failed_transaction_insert_rolls_back_the_redemption(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)
    reward = create_reward(client, adult, cost_points=50)

    redemption_id = uuid.uuid4()
    db_session.add(
        RewardRedemption(
            id=redemption_id,
            reward_id=uuid.UUID(reward["id"]),
            user_id=adult.id,
            cost_points=50,
        )
    )
    db_session.add(
        PointTransaction(
            user_id=uuid.uuid4(),  # nonexistent user -> FK violation forces failure
            redemption_id=redemption_id,
            amount=-50,
            reason=PointTransactionReason.REWARD_REDEEMED,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(RewardRedemption, redemption_id) is None


def test_failed_redemption_insert_rolls_back_the_transaction(
    client: TestClient, make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    seed_balance(db_session, adult, 100)

    db_session.add(
        RewardRedemption(
            id=uuid.uuid4(),
            reward_id=uuid.uuid4(),  # nonexistent reward -> FK violation forces failure
            user_id=adult.id,
            cost_points=50,
        )
    )
    db_session.add(
        PointTransaction(
            user_id=adult.id,
            amount=-50,
            reason=PointTransactionReason.REWARD_REDEEMED,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    txn_count = db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(
            PointTransaction.user_id == adult.id,
            PointTransaction.reason == PointTransactionReason.REWARD_REDEEMED,
        )
    )
    assert txn_count == 0
    assert balance_of(db_session, adult.id) == 100


# --- Concurrency -------------------------------------------------------------------------------


def test_concurrent_redemptions_cannot_overspend_the_balance() -> None:
    """Exercises the real Postgres row lock across two genuinely independent,
    concurrently-committing sessions -- not the shared savepoint-isolated
    `db_session`/`client` fixtures used elsewhere, since those share a single
    session/transaction and could never reproduce a real race. Data is
    created and cleaned up directly against the real database as a result.
    """
    setup_session = SessionLocal()
    adult = User(name="Concurrent Adult", role=UserRole.ADULT)
    setup_session.add(adult)
    setup_session.commit()
    setup_session.refresh(adult)

    reward = Reward(name="Contested reward", cost_points=100, created_by=adult.id)
    setup_session.add(reward)
    setup_session.commit()
    setup_session.refresh(reward)

    task = Task(
        title="Concurrency balance seed",
        reward_points=100,
        status=TaskStatus.COMPLETED,
        assigned_to=adult.id,
        created_by=adult.id,
    )
    setup_session.add(task)
    setup_session.commit()
    setup_session.refresh(task)

    setup_session.add(
        PointTransaction(
            user_id=adult.id,
            task_id=task.id,
            amount=100,
            reason=PointTransactionReason.TASK_COMPLETED,
        )
    )
    setup_session.commit()

    auth_headers = real_session_headers(setup_session, adult.id)

    try:
        results: list[int] = []
        barrier = threading.Barrier(2)

        def attempt_redeem() -> None:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = thread_client.post(
                    f"/api/rewards/{reward.id}/redeem",
                    headers=auth_headers,
                )
            results.append(response.status_code)

        threads = [threading.Thread(target=attempt_redeem) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == [201, 409]

        final_balance = setup_session.scalar(
            select(func.coalesce(func.sum(PointTransaction.amount), 0)).where(
                PointTransaction.user_id == adult.id
            )
        )
        assert final_balance == 0

        redemption_count = setup_session.scalar(
            select(func.count())
            .select_from(RewardRedemption)
            .where(RewardRedemption.user_id == adult.id)
        )
        assert redemption_count == 1
    finally:
        setup_session.rollback()
        setup_session.query(UserSession).filter_by(user_id=adult.id).delete()
        setup_session.query(PointTransaction).filter_by(user_id=adult.id).delete()
        setup_session.query(RewardRedemption).filter_by(user_id=adult.id).delete()
        setup_session.query(Task).filter_by(id=task.id).delete()
        setup_session.query(Reward).filter_by(id=reward.id).delete()
        setup_session.query(User).filter_by(id=adult.id).delete()
        setup_session.commit()
        setup_session.close()


# --- Authorization / errors ---------------------------------------------------------------------


def test_missing_identity_header_rejected(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult)

    response = client.post(f"/api/rewards/{reward['id']}/redeem")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_x_user_id_header_alone_does_not_authenticate(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult)

    # Even a real, existing user's id in X-User-Id (with no session cookie)
    # must not authenticate -- it is no longer a production auth mechanism.
    response = client.post(
        f"/api/rewards/{reward['id']}/redeem", headers={"X-User-Id": str(adult.id)}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_reward_returns_404(client: TestClient, make_user: Callable[..., User]) -> None:
    adult = make_user(ADULT)

    response = client.post(f"/api/rewards/{uuid.uuid4()}/redeem", headers=auth(adult))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REWARD_NOT_FOUND"


def test_insufficient_points_returns_409_with_expected_code(
    client: TestClient, make_user: Callable[..., User]
) -> None:
    adult = make_user(ADULT)
    reward = create_reward(client, adult, cost_points=1)

    response = client.post(f"/api/rewards/{reward['id']}/redeem", headers=auth(adult))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_POINTS"
