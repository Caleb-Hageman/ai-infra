# Purpose: Ingest router — signed PUT (/upload/init + complete), legacy multipart /upload.

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.auth import get_api_key
from app.config import EMBEDDING_DIM
from app.db import get_session
from app.models import Document, DocumentSourceType, DocumentStatus

from conftest import override_deps


def test_init_upload_401(app_client):
    response = app_client.post(
        f"/ingest/{uuid4()}/upload/init",
        json={"filename": "a.txt"},
    )
    assert response.status_code == 401


def test_init_upload_415_bad_extension(app_client, fake_session, fake_api_key):
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    async def fake_get_session():
        yield fake_session(None)

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{uuid4()}/upload/init",
            json={"filename": "bad.exe"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 415


@patch("app.routers.ingest.gcs.generate_signed_put_url", return_value="https://example.com/put")
def test_init_upload_200(mock_sign, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    async def mock_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock(return_value=None)
    mock_session.refresh = AsyncMock(side_effect=mock_refresh)

    proj = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = proj
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/init",
            json={"filename": "doc.txt", "content_type": "text/plain"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["upload_url"] == "https://example.com/put"
    assert "session_id" in data
    assert data["expires_in_seconds"] > 0
    mock_sign.assert_called_once()
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@patch("app.routers.ingest._background_ingest", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", return_value=100)
def test_complete_upload_202(mock_verify, mock_bg, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()
    now = datetime.now(timezone.utc)

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.gcs_path = "t/p/f.txt"
    mock_us.filename = "f.txt"
    mock_us.mime_type = "text/plain"
    mock_us.completed_at = None
    mock_us.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_us

    async def _refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock(return_value=None)
    mock_session.refresh = AsyncMock(side_effect=_refresh)

    doc = Document(
        id=uuid4(),
        team_id=key.team_id,
        project_id=project_id,
        title="f.txt",
        source_type=DocumentSourceType.upload,
        gcs_uri="t/p/f.txt",
        mime_type="text/plain",
        status=DocumentStatus.processing,
    )

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }), patch(
        "app.routers.ingest.create_uploaded_document",
        new_callable=AsyncMock,
        return_value=doc,
    ):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "processing"
    assert data["ingestion_progress_percent"] == 0
    assert data["chunk_count"] == 0
    assert data["latest_ingestion_job"] is None
    assert response.headers.get("X-Document-Id") == str(doc.id)
    assert response.headers.get("X-Upload-Session-Id") == str(session_id)
    mock_verify.assert_called_once_with("t/p/f.txt")
    mock_bg.assert_called_once_with(
        doc.id,
        "t/p/f.txt",
        ".txt",
        256,
        50,
    )


@patch("app.routers.ingest.insert_document_chunks", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.embed_documents", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.chunk_text", return_value=[{"chunk_index": 0, "content": "x"}])
@patch("app.routers.ingest.rag_service.extract_text", return_value="full")
@patch("app.routers.ingest.rag_service.ensure_dimension", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.upload_file_stream", return_value="gcs/path")
def test_legacy_multipart_upload_201(
    mock_gcs_stream,
    _ensure_dim,
    _extract_text,
    _chunk_text,
    mock_embed,
    mock_insert_chunks,
    app_client,
    fake_api_key,
):
    mock_embed.return_value = [[0.1] * EMBEDDING_DIM]

    key = fake_api_key()
    project_id = uuid4()
    now = datetime.now(timezone.utc)

    async def fake_get_api_key():
        return key

    async def _refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    mock_proj = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_proj
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock(return_value=None)
    mock_session.refresh = AsyncMock(side_effect=_refresh)

    doc = Document(
        id=uuid4(),
        team_id=key.team_id,
        project_id=project_id,
        title="a.txt",
        source_type=DocumentSourceType.upload,
        gcs_uri="gcs/path",
        mime_type="text/plain",
        status=DocumentStatus.uploaded,
    )

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }), patch(
        "app.routers.ingest.create_uploaded_document",
        new_callable=AsyncMock,
        return_value=doc,
    ):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("a.txt", b"hello", "text/plain")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "ready"
    assert data["ingestion_progress_percent"] == 100
    assert data["chunk_count"] == 1
    assert data["latest_ingestion_job"] is not None
    assert data["latest_ingestion_job"]["status"] == "succeeded"
    assert data["latest_ingestion_job"]["chunks_created"] == 1
    assert data["latest_ingestion_job"]["total_chunks"] == 1
    mock_gcs_stream.assert_called_once()
    mock_insert_chunks.assert_called_once()
