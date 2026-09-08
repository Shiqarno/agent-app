import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app import user_operations
from app.activation import ACTIVATION_TOKEN_TTL, InvalidActivationError, resolve_activation
from app.models import TelegramIdentity, User, UserActivation, UserRole, utcnow
from app.security import hash_token
from app.user_operations import (
    InvalidNameError,
    NotAnAdultError,
    UserAlreadyConnectedError,
    UserNotFoundError,
    create_child,
    generate_activation_token,
    get_users,
)

ADULT = UserRole.ADULT
CHILD = UserRole.CHILD


def _connect(db_session: Session, user: User, telegram_user_id: int) -> None:
    db_session.add(TelegramIdentity(user_id=user.id, telegram_user_id=telegram_user_id))
    db_session.commit()


# =========================================================================================
# get_users
# =========================================================================================


def test_adult_can_retrieve_users(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)
    child = make_user(CHILD, "Alex")

    items = get_users(db_session, adult)

    ids = {user.id for user, _ in items}
    assert adult.id in ids
    assert child.id in ids


def test_get_users_rejects_a_child(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        get_users(db_session, child)


def test_get_users_reports_connection_status(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    connected_child = make_user(CHILD, "Connected Child")
    unconnected_child = make_user(CHILD, "Unconnected Child")
    _connect(db_session, connected_child, 111222333)

    items = get_users(db_session, adult)

    status_by_id = {user.id: connected for user, connected in items}
    assert status_by_id[connected_child.id] is True
    assert status_by_id[unconnected_child.id] is False


# =========================================================================================
# create_child
# =========================================================================================


def test_adult_can_create_a_child(make_user: Callable[..., User], db_session: Session) -> None:
    adult = make_user(ADULT)

    child, token = create_child(db_session, adult, name="Alex")

    assert child.name == "Alex"
    assert child.role == CHILD
    assert isinstance(token, str)
    assert token


def test_child_cannot_create_a_child(make_user: Callable[..., User], db_session: Session) -> None:
    child = make_user(CHILD)
    with pytest.raises(NotAnAdultError):
        create_child(db_session, child, name="Someone")


def test_create_child_creates_an_activation(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    child, _token = create_child(db_session, adult, name="Alex")

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one_or_none()
    assert activation is not None


def test_create_child_activation_has_a_72_hour_expiration(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    before = utcnow()

    child, _token = create_child(db_session, adult, name="Alex")

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    assert activation.expires_at - before - ACTIVATION_TOKEN_TTL < timedelta(seconds=5)


def test_create_child_returned_token_is_usable_through_the_existing_activation_mechanism(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    child, token = create_child(db_session, adult, name="Alex")

    activation, resolved_user = resolve_activation(db_session, token)
    assert resolved_user.id == child.id
    assert activation.user_id == child.id


def test_create_child_does_not_persist_the_raw_token(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)

    child, token = create_child(db_session, adult, name="Alex")

    activation = db_session.query(UserActivation).filter_by(user_id=child.id).one()
    assert activation.token_hash != token
    assert activation.token_hash == hash_token(token)


def test_create_child_rejects_a_blank_name(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(InvalidNameError):
        create_child(db_session, adult, name="   ")


def test_create_child_is_atomic(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    """If activation creation fails, the User must not remain either --
    mirrors the existing Web transactional test (test_users.py).
    """
    adult = User(name="Setup Adult", role=ADULT)
    db_session.add(adult)
    db_session.commit()

    def _boom(db: Session, user_id: uuid.UUID) -> str:
        raise RuntimeError("simulated activation failure")

    monkeypatch.setattr(user_operations, "create_activation", _boom)

    with pytest.raises(RuntimeError):
        create_child(db_session, adult, name="Alex")

    db_session.rollback()
    assert db_session.query(User).filter_by(name="Alex").count() == 0


# =========================================================================================
# generate_activation_token
# =========================================================================================


def test_generate_activation_for_an_unconnected_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _initial_token = create_child(db_session, adult, name="Alex")

    token = generate_activation_token(db_session, adult, child.id)

    activation, resolved_user = resolve_activation(db_session, token)
    assert resolved_user.id == child.id


def test_generate_activation_invalidates_the_old_token(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, old_token = create_child(db_session, adult, name="Alex")

    generate_activation_token(db_session, adult, child.id)

    with pytest.raises(InvalidActivationError):
        resolve_activation(db_session, old_token)


def test_generate_activation_new_token_is_valid(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _old_token = create_child(db_session, adult, name="Alex")

    new_token = generate_activation_token(db_session, adult, child.id)

    activation, resolved_user = resolve_activation(db_session, new_token)
    assert resolved_user.id == child.id
    assert activation.used_at is None


def test_generate_activation_expires_in_72_hours(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _old_token = create_child(db_session, adult, name="Alex")
    before = utcnow()

    token = generate_activation_token(db_session, adult, child.id)

    activation, _ = resolve_activation(db_session, token)
    assert activation.expires_at - before - ACTIVATION_TOKEN_TTL < timedelta(seconds=5)


def test_generate_activation_rejects_a_connected_child(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _token = create_child(db_session, adult, name="Alex")
    _connect(db_session, child, 987654321)

    with pytest.raises(UserAlreadyConnectedError):
        generate_activation_token(db_session, adult, child.id)


def test_generate_activation_rejects_a_nonexistent_user(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    with pytest.raises(UserNotFoundError):
        generate_activation_token(db_session, adult, uuid.uuid4())


def test_generate_activation_rejects_a_non_adult_actor(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _token = create_child(db_session, adult, name="Alex")
    other_child = make_user(CHILD, "Other Child")

    with pytest.raises(NotAnAdultError):
        generate_activation_token(db_session, other_child, child.id)


def test_generate_activation_rejects_an_adult_target(
    make_user: Callable[..., User], db_session: Session
) -> None:
    """Issue #29 is Child onboarding specifically -- an Adult target (even
    one somehow eligible otherwise) is not a valid target for this
    operation, matching the Telegram UX which only ever offers it for
    Children.
    """
    adult = make_user(ADULT)
    other_adult = make_user(ADULT, "Other Adult")

    with pytest.raises(UserNotFoundError):
        generate_activation_token(db_session, adult, other_adult.id)


def test_generate_activation_does_not_create_a_second_activation_row(
    make_user: Callable[..., User], db_session: Session
) -> None:
    adult = make_user(ADULT)
    child, _token = create_child(db_session, adult, name="Alex")

    generate_activation_token(db_session, adult, child.id)

    count = db_session.query(UserActivation).filter_by(user_id=child.id).count()
    assert count == 1
