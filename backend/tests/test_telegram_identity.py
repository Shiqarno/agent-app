import threading
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from conftest import create_activation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activation import create_activation as insert_activation
from app.activation import regenerate_activation
from app.db import SessionLocal
from app.models import TelegramIdentity, User, UserActivation, UserCredential, UserRole, UserSession
from app.telegram_identity import (
    TelegramAccountAlreadyLinkedError,
    TelegramActivationInvalidError,
    activate_telegram_identity,
    resolve_user_by_telegram_id,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _next_telegram_id() -> int:
    """A fresh, distinct fake Telegram user id per call -- real Telegram ids
    are large 64-bit integers, so this stays well clear of any test-fixture
    numbering elsewhere.
    """
    return uuid.uuid4().int % 9_000_000_000 + 100_000_000


# =========================================================================================
# Model/integrity: DB-level uniqueness
# =========================================================================================


def test_one_user_cannot_have_two_telegram_identities(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    db_session.add(TelegramIdentity(user_id=child.id, telegram_user_id=_next_telegram_id()))
    db_session.commit()

    db_session.add(TelegramIdentity(user_id=child.id, telegram_user_id=_next_telegram_id()))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_one_telegram_account_cannot_belong_to_two_users(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    shared_telegram_id = _next_telegram_id()
    db_session.add(TelegramIdentity(user_id=child_a.id, telegram_user_id=shared_telegram_id))
    db_session.commit()

    db_session.add(TelegramIdentity(user_id=child_b.id, telegram_user_id=shared_telegram_id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# =========================================================================================
# Activation: Case A -- no existing TelegramIdentity
# =========================================================================================


def test_valid_activation_connects_account(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)
    telegram_id = _next_telegram_id()

    user = activate_telegram_identity(db_session, token, telegram_id)

    assert user.id == child.id
    identity = db_session.query(TelegramIdentity).filter_by(user_id=child.id).one_or_none()
    assert identity is not None
    assert identity.telegram_user_id == telegram_id


def test_activation_marks_the_token_used(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    activate_telegram_identity(db_session, token, _next_telegram_id())

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    assert activation.used_at is not None


def test_activation_does_not_create_web_credentials(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    activate_telegram_identity(db_session, token, _next_telegram_id())

    credential = db_session.query(UserCredential).filter_by(user_id=child.id).one_or_none()
    assert credential is None


def test_activation_does_not_create_web_session(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)

    activate_telegram_identity(db_session, token, _next_telegram_id())

    session = db_session.query(UserSession).filter_by(user_id=child.id).one_or_none()
    assert session is None


# =========================================================================================
# Activation: Case E -- invalid / expired / used
# =========================================================================================


def test_expired_activation_does_not_connect(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child, expires_in=timedelta(seconds=-1))

    with pytest.raises(TelegramActivationInvalidError):
        activate_telegram_identity(db_session, token, _next_telegram_id())

    identity = db_session.query(TelegramIdentity).filter_by(user_id=child.id).one_or_none()
    assert identity is None


def test_already_used_activation_does_not_connect(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    token = create_activation(child)
    activate_telegram_identity(db_session, token, _next_telegram_id())

    with pytest.raises(TelegramActivationInvalidError):
        activate_telegram_identity(db_session, token, _next_telegram_id())


def test_nonexistent_token_does_not_connect(db_session: Session) -> None:
    with pytest.raises(TelegramActivationInvalidError):
        activate_telegram_identity(db_session, "not-a-real-token", _next_telegram_id())


# =========================================================================================
# Activation: Case B -- same account, already connected (idempotent)
# =========================================================================================


def test_reactivating_with_the_same_telegram_account_is_idempotent(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    telegram_id = _next_telegram_id()
    first_token = create_activation(child)
    activate_telegram_identity(db_session, first_token, telegram_id)

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    second_token = regenerate_activation(activation)
    db_session.commit()

    user = activate_telegram_identity(db_session, second_token, telegram_id)

    assert user.id == child.id
    identities = db_session.query(TelegramIdentity).filter_by(user_id=child.id).all()
    assert len(identities) == 1
    assert identities[0].telegram_user_id == telegram_id


# =========================================================================================
# Activation: Case C -- reconnect (different account, same intended User)
# =========================================================================================


def test_reconnect_replaces_the_existing_identity(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    old_telegram_id = _next_telegram_id()
    first_token = create_activation(child)
    activate_telegram_identity(db_session, first_token, old_telegram_id)

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    reconnect_token = regenerate_activation(activation)
    db_session.commit()
    new_telegram_id = _next_telegram_id()

    user = activate_telegram_identity(db_session, reconnect_token, new_telegram_id)

    assert user.id == child.id
    identities = db_session.query(TelegramIdentity).filter_by(user_id=child.id).all()
    assert len(identities) == 1
    assert identities[0].telegram_user_id == new_telegram_id
    assert resolve_user_by_telegram_id(db_session, old_telegram_id) is None
    resolved = resolve_user_by_telegram_id(db_session, new_telegram_id)
    assert resolved is not None
    assert resolved.id == child.id


def test_failed_reconnect_leaves_the_old_identity_unchanged(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    old_telegram_id = _next_telegram_id()
    first_token = create_activation(child)
    activate_telegram_identity(db_session, first_token, old_telegram_id)

    # A regenerated-but-expired activation for the same user (UserActivation
    # is one-per-user, so reuse+expire the existing row rather than trying
    # to insert a second one) -- the reconnect attempt must fail without
    # touching the existing, still-valid identity.
    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    expired_token = regenerate_activation(activation)
    activation.expires_at = activation.expires_at - timedelta(hours=73)
    db_session.commit()

    with pytest.raises(TelegramActivationInvalidError):
        activate_telegram_identity(db_session, expired_token, _next_telegram_id())

    identity = db_session.query(TelegramIdentity).filter_by(user_id=child.id).one()
    assert identity.telegram_user_id == old_telegram_id


# =========================================================================================
# Activation: Case D -- Telegram account already belongs to another User
# =========================================================================================


def test_telegram_account_belonging_to_another_user_is_not_reassigned(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child_a = make_user(CHILD, "Child A")
    child_b = make_user(CHILD, "Child B")
    telegram_id = _next_telegram_id()
    token_a = create_activation(child_a)
    activate_telegram_identity(db_session, token_a, telegram_id)

    token_b = create_activation(child_b)
    with pytest.raises(TelegramAccountAlreadyLinkedError):
        activate_telegram_identity(db_session, token_b, telegram_id)

    # Child A's identity is untouched, and Child B still has none.
    identity_a = db_session.query(TelegramIdentity).filter_by(user_id=child_a.id).one()
    assert identity_a.telegram_user_id == telegram_id
    identity_b = db_session.query(TelegramIdentity).filter_by(user_id=child_b.id).one_or_none()
    assert identity_b is None


# =========================================================================================
# Identity resolution
# =========================================================================================


def test_resolve_connected_telegram_account_returns_the_user(
    make_user: Callable[..., User], db_session: Session
) -> None:
    child = make_user(CHILD)
    telegram_id = _next_telegram_id()
    token = create_activation(child)
    activate_telegram_identity(db_session, token, telegram_id)

    resolved = resolve_user_by_telegram_id(db_session, telegram_id)

    assert resolved is not None
    assert resolved.id == child.id


def test_resolve_unknown_telegram_account_returns_none(db_session: Session) -> None:
    assert resolve_user_by_telegram_id(db_session, _next_telegram_id()) is None


# =========================================================================================
# Concurrency
# =========================================================================================


def test_concurrent_activation_attempts_for_the_same_telegram_account_claim_it_exactly_once() -> (
    None
):
    """Two different Users, each with their own valid activation, racing to
    connect the *same* Telegram account. Real independently-committing
    sessions (not the shared savepoint-isolated db_session fixture) against
    the real running app, matching this project's established concurrency
    test pattern. Exactly one must win; the final database state must never
    violate the telegram_user_id uniqueness invariant.
    """
    setup_session = SessionLocal()
    user_x = User(name="Concurrent Telegram X", role=CHILD)
    user_y = User(name="Concurrent Telegram Y", role=CHILD)
    setup_session.add_all([user_x, user_y])
    setup_session.commit()
    setup_session.refresh(user_x)
    setup_session.refresh(user_y)

    token_x = insert_activation(setup_session, user_x.id)
    token_y = insert_activation(setup_session, user_y.id)
    setup_session.commit()

    shared_telegram_id = _next_telegram_id()

    try:
        results: list[tuple[str, object]] = []
        barrier = threading.Barrier(2)

        def attempt(token: str) -> None:
            barrier.wait()
            session = SessionLocal()
            try:
                user = activate_telegram_identity(session, token, shared_telegram_id)
                results.append(("success", user.id))
            except TelegramAccountAlreadyLinkedError:
                results.append(("conflict", None))
            finally:
                session.close()

        threads = [
            threading.Thread(target=attempt, args=(token_x,)),
            threading.Thread(target=attempt, args=(token_y,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        outcomes = sorted(status for status, _ in results)
        assert outcomes == ["conflict", "success"]

        setup_session.expire_all()
        identities = (
            setup_session.query(TelegramIdentity)
            .filter_by(telegram_user_id=shared_telegram_id)
            .all()
        )
        assert len(identities) == 1
        winner_id = next(uid for status, uid in results if status == "success")
        assert identities[0].user_id == winner_id
    finally:
        setup_session.rollback()
        setup_session.query(TelegramIdentity).filter(
            TelegramIdentity.user_id.in_([user_x.id, user_y.id])
        ).delete(synchronize_session=False)
        setup_session.query(UserActivation).filter(
            UserActivation.user_id.in_([user_x.id, user_y.id])
        ).delete(synchronize_session=False)
        setup_session.query(User).filter(User.id.in_([user_x.id, user_y.id])).delete(
            synchronize_session=False
        )
        setup_session.commit()
        setup_session.close()
