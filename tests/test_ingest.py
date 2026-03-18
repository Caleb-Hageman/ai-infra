# Purpose: Ingest router tests (upload_file auth, invalid type, success with mocks).

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.auth import get_api_key
from app.db import get_session

from conftest import override_deps


def test_upload_file_401_without_key(app_client):
    project_id = uuid4()
    response = app_client.post(
        f"/ingest/{project_id}/upload",
        files={"file": ("test.pdf", b"content", "application/pdf")},
    )
    assert response.status_code == 401


def test_upload_file_415_for_invalid_file_type(app_client, fake_session, fake_api_key):
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("virus.exe", b"x", "application/octet-stream")},
        )
    assert response.status_code == 415


@patch("app.routers.ingest.insert_document_chunks", new_callable=AsyncMock)
@patch("app.routers.ingest.rag_service")
@patch("app.routers.ingest.document.create_uploaded_document", new_callable=AsyncMock)
@patch("app.routers.ingest.gcs.upload_file_stream")
def test_upload_file_201_with_mocked_gcs_and_insert(
    mock_gcs, mock_create_doc, mock_rag, mock_insert, app_client, fake_session, fake_api_key
):
    mock_gcs.return_value = "team/project/test.txt"
    mock_doc = MagicMock()
    mock_doc.id = uuid4()
    mock_doc.team_id = uuid4()
    mock_doc.project_id = uuid4()
    mock_doc.title = "test.txt"
    mock_doc.source_type = "upload"
    mock_doc.gcs_uri = "team/project/test.txt"
    mock_doc.status = "ready"
    mock_create_doc.return_value = mock_doc

    mock_rag.extract_text.return_value = "sample text"
    mock_rag.chunk_text.return_value = [{"content": "sample text", "chunk_index": 0}]
    mock_rag.ensure_dimension = AsyncMock(return_value=None)
    mock_rag.embed_documents = AsyncMock(return_value=[[0.1] * 1536])

    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.post(
            f"/ingest/{project_id}/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "test.txt"
    assert data["status"] == "ready"
    mock_gcs.assert_called_once()
    mock_create_doc.assert_called_once()
    mock_insert.assert_called_once()
