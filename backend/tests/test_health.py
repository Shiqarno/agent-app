import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import db
from app.main import app

client = TestClient(app)


def test_health_returns_200_when_database_available() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_application_and_database_status() -> None:
    response = client.get("/health")
    assert response.json() == {"status": "ok", "database": "ok"}


def test_database_is_available_checks_a_real_connection() -> None:
    assert db.database_is_available() is True


def test_health_returns_503_when_database_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    unreachable_engine = create_engine("postgresql+psycopg://app:app@localhost:1/app", future=True)
    monkeypatch.setattr(db, "engine", unreachable_engine)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


def test_database_is_available_returns_false_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable_engine = create_engine("postgresql+psycopg://app:app@localhost:1/app", future=True)
    monkeypatch.setattr(db, "engine", unreachable_engine)

    assert db.database_is_available() is False
