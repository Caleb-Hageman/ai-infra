# Purpose: Shared pytest fixtures for API tests (fake session, api key, TestClient).

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.routers import metrics
from app.auth import get_api_key
from app.db import get_session
from app.main import app


@contextmanager
def override_deps(overrides: dict):
    """Temporarily set app.dependency_overrides, then restore."""
    for dep, impl in overrides.items():
        app.dependency_overrides[dep] = impl
    try:
        yield
    finally:
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)


async def _mock_refresh(obj):
    if getattr(obj, "id", None) is None:
        obj.id = uuid4()
    if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
        obj.created_at = datetime.now(timezone.utc)


@pytest.fixture
def fake_session():
    """Factory: returns async generator yielding mock AsyncSession.
    Call with get_result=... for session.get return value.
    Call with execute_result=[...] for session.execute().scalars().all() return value.
    """

    def _make(get_result=None, execute_result=None):
        session = MagicMock()
        session.get = AsyncMock(return_value=get_result)
        session.add = MagicMock()
        session.commit = AsyncMock(return_value=None)
        session.refresh = AsyncMock(side_effect=_mock_refresh)

        if execute_result is not None:
            mock_result = MagicMock()
            mock_result.scalars().all.return_value = execute_result
            session.execute = AsyncMock(return_value=mock_result)
        else:
            session.execute = AsyncMock(return_value=MagicMock())

        async def _gen():
            yield session

        return _gen

    return _make


_USE_DEFAULT = object()


@pytest.fixture
def fake_api_key():
    """Factory: returns mock ApiKey. Call with team_id=... for configurable team_id. Use team_id=None for no-RAG path."""

    def _make(team_id=_USE_DEFAULT):
        key = MagicMock()
        key.team_id = uuid4() if team_id is _USE_DEFAULT else team_id
        return key

    return _make


def mock_vllm_client(captured_prompt=None):
    """Return mock httpx.AsyncClient that captures prompt and returns fake vLLM response."""
    captured = captured_prompt if captured_prompt is not None else []

    async def mock_post(url, json=None, **kwargs):
        if json:
            if "messages" in json:
                captured.append(json["messages"][0]["content"])
            elif "prompt" in json:
                captured.append(json["prompt"])
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=mock_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client

@pytest.fixture
def app_client():
    """TestClient for the FastAPI app with test middleware."""

    # 1. Remove existing middleware
    app.user_middleware.clear()
    app.middleware_stack = None  #force rebuild

    mock_session = MagicMock()
    proj = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = proj
    mock_session.commit = AsyncMock(return_value=None)    
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    # 2. Add test version
    app.add_middleware(
        metrics.ApiUsageMiddleware,
        session_provider=fake_get_session,
    )

    # 3. Create client AFTER middleware change
    with TestClient(app) as client:
        yield client
#@pytest.fixture
#def app_client():
#    """TestClient for the FastAPI app. Use override_deps() to inject mocks."""
#    with TestClient(app) as client:
#        yield client
#



@pytest.fixture(autouse=True)
def mock_chat_rate_limiter():
    """Chat router rate limiting uses Redis; tests run without a local Redis."""
    with patch(
        "app.routers.chat.rate_limiter.is_rate_limited",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = False
        yield m
