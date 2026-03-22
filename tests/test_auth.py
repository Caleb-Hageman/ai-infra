# Purpose: Auth behavior for protected routes (missing header, invalid key, valid key).

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.auth import get_api_key
from app.db import get_session

from conftest import override_deps


def test_get_api_key_returns_key_when_session_has_match(app_client):
    """Exercises real get_api_key: session.execute returns ApiKey from DB lookup."""
    mock_result = MagicMock()
    key = MagicMock()
    key.team_id = uuid4()
    mock_result.scalar_one_or_none.return_value = key

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield session

    with patch("app.routers.chat.chat_service.generate_response", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = ("ok", [])
        with override_deps({get_session: fake_get_session}):
            response = app_client.post(
                "/api/v1/chat",
                json={"question": "test"},
                headers={"Authorization": "Bearer sk-valid"},
            )
    assert response.status_code == 200
    session.execute.assert_called_once()


def test_get_api_key_raises_401_when_session_returns_none(app_client):
    """Exercises real get_api_key: session.execute returns None (invalid/revoked key)."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield session

    with override_deps({get_session: fake_get_session}):
        response = app_client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers={"Authorization": "Bearer sk-invalid"},
        )
    assert response.status_code == 401
    session.execute.assert_called_once()


def test_missing_authorization_header_returns_401(app_client):
    response = app_client.post("/api/v1/chat", json={"question": "test"})
    assert response.status_code == 401


def test_invalid_or_revoked_key_returns_401(app_client):
    async def fake_get_api_key_401():
        raise HTTPException(401, "Invalid or revoked API key")

    with override_deps({get_api_key: fake_get_api_key_401}):
        response = app_client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401


def test_valid_key_passes_through(app_client, fake_session, fake_api_key):
    with patch("app.routers.chat.chat_service.generate_response", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = ("ok", [])

        key = fake_api_key()

        async def fake_get_api_key():
            return key

        with override_deps({
            get_api_key: fake_get_api_key,
            get_session: fake_session(None),
        }):
            response = app_client.post(
                "/api/v1/chat",
                json={"question": "test"},
                headers={"Authorization": "Bearer sk-test"},
            )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
