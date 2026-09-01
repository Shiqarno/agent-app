import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Project


def test_create_project_returns_201(client: TestClient) -> None:
    response = client.post(
        "/api/projects", json={"name": "My project", "description": "A test project"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My project"
    assert body["description"] == "A test project"
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_create_project_with_empty_name_is_rejected(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": ""})

    assert response.status_code == 422


def test_create_project_with_whitespace_only_name_is_rejected(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "   "})

    assert response.status_code == 422


def test_list_projects_returns_created_projects(client: TestClient) -> None:
    client.post("/api/projects", json={"name": "First"})
    client.post("/api/projects", json={"name": "Second"})

    response = client.get("/api/projects")

    assert response.status_code == 200
    names = [project["name"] for project in response.json()]
    assert names == ["First", "Second"]


def test_list_projects_returns_empty_array_when_none_exist(client: TestClient) -> None:
    response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_get_existing_project_returns_200(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "My project"}).json()

    response = client.get(f"/api/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_missing_project_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_update_existing_project(client: TestClient) -> None:
    created = client.post(
        "/api/projects", json={"name": "Original", "description": "Original description"}
    ).json()

    response = client.put(
        f"/api/projects/{created['id']}",
        json={"name": "Updated", "description": "Updated description"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Updated"
    assert body["description"] == "Updated description"


def test_update_changes_updated_at(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "Original"}).json()

    response = client.put(f"/api/projects/{created['id']}", json={"name": "Updated"})

    assert response.status_code == 200
    assert response.json()["updated_at"] != created["updated_at"]


def test_update_missing_project_returns_404(client: TestClient) -> None:
    response = client.put(f"/api/projects/{uuid.uuid4()}", json={"name": "Updated"})

    assert response.status_code == 404


def test_delete_existing_project(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "To delete"}).json()

    response = client.delete(f"/api/projects/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""


def test_deleted_project_is_no_longer_returned(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "To delete"}).json()
    client.delete(f"/api/projects/{created['id']}")

    response = client.get(f"/api/projects/{created['id']}")

    assert response.status_code == 404


def test_delete_missing_project_returns_404(client: TestClient) -> None:
    response = client.delete(f"/api/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_project_data_persists_across_separate_sessions(
    client: TestClient, db_session: Session
) -> None:
    created = client.post("/api/projects", json={"name": "Persisted project"}).json()

    other_session = Session(bind=db_session.get_bind())
    try:
        fetched = other_session.get(Project, uuid.UUID(created["id"]))
        assert fetched is not None
        assert fetched.name == "Persisted project"
    finally:
        other_session.close()
