# Purpose: GET /warmup and warmup orchestration.

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

from app.warmup import warmup_all_ok, warmup_dependencies


def test_warmup_all_ok_requires_database_embeddings_and_vllm():
    assert not warmup_all_ok({
        "database": {"ok": True},
        "embeddings": {"ok": True},
        "vllm": {"ok": False},
    })
    assert not warmup_all_ok({"database": {"ok": True}, "embeddings": {"ok": False}, "vllm": {"ok": True}})
    assert warmup_all_ok({
        "database": {"ok": True},
        "embeddings": {"ok": True},
        "vllm": {"ok": True},
    })


@patch("app.warmup.warmup_vllm", new_callable=AsyncMock)
@patch("app.warmup.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_warmup_dependencies_runs_db_and_embeddings(mock_ensure, mock_vllm_warmup):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_cm)
    mock_ensure.return_value = None

    with patch("app.warmup.engine", mock_engine):
        status = await warmup_dependencies()
        await asyncio.sleep(0)

    assert status["database"]["ok"] is True
    assert status["embeddings"]["ok"] is True
    assert status["vllm"]["ok"] is True
    assert status["vllm"].get("kickstarted") is True
    assert "storage" not in status
    mock_ensure.assert_called_once()
    mock_vllm_warmup.assert_called_once()


def test_get_warmup_503_when_not_ok(app_client):
    async def fail_warmup():
        return {
            "database": {"ok": False, "error": "no db"},
            "embeddings": {"ok": False, "error": "no model"},
            "vllm": {"ok": False, "error": "no vllm"},
        }

    with patch("app.main.warmup_mod.warmup_dependencies", fail_warmup):
        response = app_client.get("/warmup")
    assert response.status_code == 503


def test_get_warmup_200_when_ok(app_client):
    async def ok_warmup():
        return {
            "database": {"ok": True},
            "embeddings": {"ok": True, "model_dim": 1024, "expected_dim": 1024},
            "vllm": {"ok": True, "kickstarted": True},
        }

    with patch("app.main.warmup_mod.warmup_dependencies", ok_warmup):
        response = app_client.get("/warmup")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "warmed"
    assert "components" in data
