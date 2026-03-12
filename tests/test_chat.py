from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_api_key
from app.db import get_session
from app.main import app

client = TestClient(app)


def test_no_auth_returns_403():
    response = client.post("/api/v1/chat", json={"question": "test"})
    assert response.status_code == 401


def test_invalid_api_key_returns_401():
    async def fake_get_api_key_401():
        raise HTTPException(401, "Invalid or revoked API key")

    app.dependency_overrides[get_api_key] = fake_get_api_key_401
    try:
        response = client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers={"Authorization": "Bearer invalid"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_api_key, None)


@patch("app.routers.chat.chat_service.generate_response", new_callable=AsyncMock)
def test_valid_key_returns_200(mock_gen):
    mock_gen.return_value = ("mocked answer", [])

    fake_key = MagicMock()
    fake_key.team_id = uuid4()

    async def fake_get_api_key():
        return fake_key

    async def fake_get_session():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)
        yield session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_get_session
    try:
        response = client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers={"Authorization": "Bearer sk-test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["answer"] == "mocked answer"
        assert data["citations"] == []
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)


def test_project_id_wrong_team_returns_403():
    team_a = uuid4()
    team_b = uuid4()
    project_id = uuid4()

    fake_key = MagicMock()
    fake_key.team_id = team_a

    fake_project = MagicMock()
    fake_project.team_id = team_b

    async def fake_get_api_key():
        return fake_key

    async def fake_get_session():
        session = MagicMock()
        session.get = AsyncMock(return_value=fake_project)
        yield session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_get_session
    try:
        response = client.post(
            "/api/v1/chat",
            json={"question": "test", "project_id": str(project_id)},
            headers={"Authorization": "Bearer sk-test"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)


def test_project_id_not_found_returns_404():
    fake_key = MagicMock()
    fake_key.team_id = uuid4()

    async def fake_get_api_key():
        return fake_key

    async def fake_get_session():
        session = MagicMock()
        session.get = AsyncMock(return_value=None)

        yield session

    app.dependency_overrides[get_api_key] = fake_get_api_key
    app.dependency_overrides[get_session] = fake_get_session
    try:
        response = client.post(
            "/api/v1/chat",
            json={"question": "test", "project_id": str(uuid4())},
            headers={"Authorization": "Bearer sk-test"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_api_key, None)
        app.dependency_overrides.pop(get_session, None)
