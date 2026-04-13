# Purpose: Ingest router branches — errors, repair-embeddings, background task.

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.auth import get_api_key
from app.db import get_session
from app.models import Document, DocumentSourceType, DocumentStatus

from conftest import override_deps


def _session_with_project():
    proj = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = proj
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock(return_value=None)
    mock_session.refresh = AsyncMock()

    async def fake_get_session():
        yield mock_session

    return mock_session, fake_get_session


def test_init_upload_404_when_project_not_in_team(app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/init",
            json={"filename": "a.txt"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404


@patch("app.routers.ingest.gcs.generate_signed_put_url", side_effect=RuntimeError("no bucket"))
def test_init_upload_500_when_signed_url_fails(_mock_sign, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/init",
            json={"filename": "a.txt"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 500


def test_init_upload_400_invalid_filename_path(app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/init",
            json={"filename": "bad..name.txt"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 400


@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", return_value=100)
def test_complete_upload_404_unknown_session(mock_verify, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404
    mock_verify.assert_not_called()


@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", return_value=100)
def test_complete_upload_409_when_already_completed(mock_verify, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.completed_at = datetime.now(timezone.utc)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_us
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 409
    mock_verify.assert_not_called()


@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", return_value=100)
def test_complete_upload_410_when_expired(mock_verify, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.completed_at = None
    mock_us.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_us
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 410
    mock_verify.assert_not_called()


@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", side_effect=FileNotFoundError)
def test_complete_upload_400_when_object_missing_in_gcs(mock_verify, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.completed_at = None
    mock_us.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_us.filename = "f.txt"
    mock_us.gcs_path = "p"
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_us
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 400
    mock_verify.assert_called_once()


@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", side_effect=ValueError("too big"))
def test_complete_upload_413_when_size_invalid(mock_verify, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.completed_at = None
    mock_us.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    mock_us.filename = "f.txt"
    mock_us.gcs_path = "p"
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_us
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload/{session_id}/complete",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 413
    assert "too big" in response.json()["detail"]


@patch("app.routers.ingest._background_ingest", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.verify_uploaded_blob_size", return_value=100)
def test_complete_upload_expires_at_naive_normalized(mock_verify, mock_bg, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()
    session_id = uuid4()
    now = datetime.now(timezone.utc)

    async def fake_get_api_key():
        return key

    mock_us = MagicMock()
    mock_us.completed_at = None
    mock_us.expires_at = datetime(2099, 1, 1)
    mock_us.filename = "f.txt"
    mock_us.gcs_path = "p"
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
        gcs_uri="p",
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


def test_legacy_upload_415_bad_extension(app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("x.exe", b"x", "application/octet-stream")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 415


def test_legacy_upload_404_no_project(app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("a.txt", b"h", "text/plain")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404


@patch("app.routers.ingest.gcs.upload_file_stream", side_effect=OSError("upstream"))
def test_legacy_upload_500_gcs_fails(_mock_gcs, app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("a.txt", b"h", "text/plain")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 500


@patch("app.routers.ingest.insert_document_chunks", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.embed_documents", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.chunk_text", return_value=[{"chunk_index": 0, "content": "x"}])
@patch("app.routers.ingest.rag_service.extract_text", side_effect=ValueError("bad extract"))
@patch("app.routers.ingest.rag_service.ensure_dimension", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.upload_file_stream", return_value="g/p")
def test_legacy_upload_422_on_value_error(
    _gcs,
    _ensure,
    _extract,
    _chunk,
    _embed,
    _insert,
    app_client,
    fake_api_key,
):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }), patch(
        "app.routers.ingest.create_uploaded_document",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_doc = MagicMock()
        mock_doc.id = uuid4()
        mock_create.return_value = mock_doc
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("a.txt", b"h", "text/plain")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 422


@patch("app.routers.ingest.insert_document_chunks", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.embed_documents", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service.chunk_text", return_value=[{"chunk_index": 0, "content": "x"}])
@patch("app.routers.ingest.rag_service.extract_text", return_value="ok")
@patch("app.routers.ingest.rag_service.ensure_dimension", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.upload_file_stream", return_value="g/p")
def test_legacy_upload_500_on_generic_ingest_error(
    _gcs,
    _ensure,
    _extract,
    _chunk,
    mock_embed,
    _insert,
    app_client,
    fake_api_key,
):
    mock_embed.side_effect = RuntimeError("embed down")
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_session, fake_get_session = _session_with_project()

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }), patch(
        "app.routers.ingest.create_uploaded_document",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_doc = MagicMock()
        mock_doc.id = uuid4()
        mock_doc.status = None
        mock_create.return_value = mock_doc
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("a.txt", b"h", "text/plain")},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 500
    mock_session.commit.assert_called()


def test_repair_embeddings_empty_project(app_client, fake_api_key):
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/repair-embeddings",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    assert "No NULL embeddings" in response.json()["message"]


@patch("app.routers.ingest.rag_service.embed_documents", new_callable=AsyncMock)
def test_repair_embeddings_updates_batches(mock_embed, app_client, fake_api_key):
    mock_embed.return_value = [[0.1] * 1024]
    key = fake_api_key()
    project_id = uuid4()

    async def fake_get_api_key():
        return key

    chunks = [MagicMock(content="a") for _ in range(3)]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = chunks
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock(return_value=None)

    async def fake_get_session():
        yield mock_session

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_get_session,
    }):
        response = app_client.post(
            f"/ingest/{project_id}/repair-embeddings",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    assert "Successfully updated 3 chunks" in response.json()["message"]
    assert mock_embed.call_count == 1


@pytest.mark.asyncio
async def test_background_ingest_logs_when_pipeline_raises():
    from app.routers import ingest as ingest_mod

    doc_id = uuid4()
    mock_db_session = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(ingest_mod, "async_session", MagicMock(return_value=mock_ctx)),
        patch.object(
            ingest_mod,
            "process_uploaded_document",
            new_callable=AsyncMock,
            side_effect=RuntimeError("bg fail"),
        ),
    ):
        await ingest_mod._background_ingest(doc_id, "gcs", ".txt", 256, 50)
