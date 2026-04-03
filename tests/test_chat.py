import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.auth import get_api_key
from app.db import get_session

from conftest import override_deps


def test_no_auth_returns_403(app_client):
    response = app_client.post("/api/v1/chat", json={"question": "test"})
    assert response.status_code == 401


def test_invalid_api_key_returns_401(app_client):
    async def fake_get_api_key_401():
        raise HTTPException(401, "Invalid or revoked API key")

    with override_deps({get_api_key: fake_get_api_key_401}):
        response = app_client.post(
            "/api/v1/chat",
            json={"question": "test"},
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401


@patch("app.routers.chat.chat_service.generate_response", new_callable=AsyncMock)
def test_valid_key_returns_200(mock_gen, app_client, fake_session, fake_api_key):
    mock_gen.return_value = ("mocked answer", [])

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
    data = response.json()
    assert data["status"] == "success"
    assert data["answer"] == "mocked answer"
    assert data["citations"] == []


@patch("app.routers.chat.rate_limiter.is_rate_limited", new_callable=AsyncMock)
def test_redis_unavailable_returns_503(mock_rl, app_client, fake_session, fake_api_key):
    import redis.exceptions

    mock_rl.side_effect = redis.exceptions.ConnectionError(
        "Error 111 connecting to localhost:6379. Connection refused."
    )
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
    assert response.status_code == 503
    assert response.json()["detail"] == "Rate limiting backend unavailable"


def test_project_id_wrong_team_returns_403(app_client, fake_session, fake_api_key):
    team_a = uuid4()
    team_b = uuid4()
    project_id = uuid4()

    fake_project = type("Project", (), {"team_id": team_b})()
    key = fake_api_key(team_id=team_a)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(fake_project),
    }):
        response = app_client.post(
            "/api/v1/chat",
            json={"question": "test", "project_id": str(project_id)},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 403


def test_project_id_not_found_returns_404(app_client, fake_session, fake_api_key):
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.post(
            "/api/v1/chat",
            json={"question": "test", "project_id": str(uuid4())},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404


@patch("app.routers.chat.chat_service.generate_response", new_callable=AsyncMock)
def test_rag_path_project_id_calls_generate_response_with_session_project_question(
    mock_gen, app_client, fake_session, fake_api_key
):
    mock_gen.return_value = ("mocked", [])
    project_id = uuid4()
    team_id = uuid4()
    fake_project = type("Project", (), {"team_id": team_id})()
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(fake_project),
    }):
        app_client.post(
            "/api/v1/chat",
            json={"question": "rag question", "project_id": str(project_id)},
            headers={"Authorization": "Bearer sk-test"},
        )
    mock_gen.assert_called_once()
    call_args = mock_gen.call_args[0]
    assert call_args[2] == project_id
    assert call_args[3] == "rag question"


@patch("app.services.chat.httpx.AsyncClient")
def test_team_fallback_calls_execute_similarity_search_for_team(
    mock_client_cls, app_client, fake_session, fake_api_key
):
    from conftest import mock_vllm_client

    captured = []
    mock_client_cls.return_value = mock_vllm_client(captured)

    with patch(
        "app.services.chat.query_service.execute_similarity_search_for_team",
        new_callable=AsyncMock,
    ) as mock_team_search:
        mock_team_search.return_value = []

        key = fake_api_key()

        async def fake_get_api_key():
            return key

        with override_deps({
            get_api_key: fake_get_api_key,
            get_session: fake_session(None),
        }):
            response = app_client.post(
                "/api/v1/chat",
                json={"question": "team question"},
                headers={"Authorization": "Bearer sk-test"},
            )
    assert response.status_code == 200
    mock_team_search.assert_called_once()
    call_kw = mock_team_search.call_args[1]
    assert call_kw["team_id"] == key.team_id
    assert call_kw["query_text"] == "team question"


@patch("app.services.chat.httpx.AsyncClient")
def test_no_rag_path_plain_prompt_when_neither_project_nor_team(
    mock_client_cls, app_client, fake_session, fake_api_key
):
    from conftest import mock_vllm_client

    captured = []
    mock_client_cls.return_value = mock_vllm_client(captured)

    with patch(
        "app.services.chat.query_service.execute_similarity_search",
        new_callable=AsyncMock,
    ) as mock_project_search, patch(
        "app.services.chat.query_service.execute_similarity_search_for_team",
        new_callable=AsyncMock,
    ) as mock_team_search:
        key = fake_api_key(team_id=None)

        async def fake_get_api_key():
            return key

        with override_deps({
            get_api_key: fake_get_api_key,
            get_session: fake_session(None),
        }):
            response = app_client.post(
                "/api/v1/chat",
                json={"question": "plain question"},
                headers={"Authorization": "Bearer sk-test"},
            )
    assert response.status_code == 200
    mock_project_search.assert_not_called()
    mock_team_search.assert_not_called()
    assert len(captured) == 1
    assert captured[0] == "plain question"


@pytest.mark.asyncio
@patch("app.services.chat._get_id_token_headers", return_value={})
@patch("app.services.chat.httpx.AsyncClient")
async def test_warmup_vllm_posts_minimal_chat_completion(mock_client_cls, _mock_headers):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client_cls.return_value = mock_client

    from app.services.chat import warmup_vllm

    await warmup_vllm()

    mock_client.post.assert_called_once()
    url = mock_client.post.call_args[0][0]
    payload = mock_client.post.call_args[1]["json"]
    assert "/v1/chat/completions" in url
    assert payload["max_tokens"] == 1
    assert payload["messages"][0]["content"] == "."
