import importlib
from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ReloadApp = Callable[[dict[str, str]], FastAPI]


@pytest.fixture
def reload_app_with_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[ReloadApp]:
    def _reload(env: dict[str, str]) -> FastAPI:
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        import app.config
        import app.main

        importlib.reload(app.config)
        importlib.reload(app.main)
        return app.main.app

    yield _reload

    import app.config
    import app.main

    importlib.reload(app.config)
    importlib.reload(app.main)


def test_cors_allows_the_configured_origin(
    reload_app_with_env: ReloadApp,
) -> None:
    test_app = reload_app_with_env({"CORS_ORIGINS": "http://example.test"})
    client = TestClient(test_app)

    response = client.get("/health", headers={"Origin": "http://example.test"})

    assert response.headers.get("access-control-allow-origin") == "http://example.test"


def test_cors_rejects_an_origin_not_in_configuration(
    reload_app_with_env: ReloadApp,
) -> None:
    test_app = reload_app_with_env({"CORS_ORIGINS": "http://example.test"})
    client = TestClient(test_app)

    response = client.get("/health", headers={"Origin": "http://not-allowed.test"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_reflects_a_changed_configured_origin(
    reload_app_with_env: ReloadApp,
) -> None:
    first_app = reload_app_with_env({"CORS_ORIGINS": "http://first.test"})
    first_client = TestClient(first_app)
    first_response = first_client.get("/health", headers={"Origin": "http://first.test"})
    assert first_response.headers.get("access-control-allow-origin") == "http://first.test"

    second_app = reload_app_with_env({"CORS_ORIGINS": "http://second.test"})
    second_client = TestClient(second_app)

    rejects_old_origin = second_client.get("/health", headers={"Origin": "http://first.test"})
    assert "access-control-allow-origin" not in rejects_old_origin.headers

    allows_new_origin = second_client.get("/health", headers={"Origin": "http://second.test"})
    assert allows_new_origin.headers.get("access-control-allow-origin") == "http://second.test"
