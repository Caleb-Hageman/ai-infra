# Purpose: Query router tests (similarity_search, list_documents, get_document, list_chunks, delete_document, stats).

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.auth import get_api_key
from app.db import get_session

from conftest import override_deps


def _fake_doc(**kwargs):
    defaults = {
        "id": uuid4(),
        "team_id": uuid4(),
        "project_id": uuid4(),
        "title": "doc.pdf",
        "source_type": "upload",
        "gcs_uri": None,
        "status": "uploaded",
    }
    defaults.update(kwargs)
    return type("Document", (), defaults)()


def _fake_chunk(**kwargs):
    defaults = {
        "id": uuid4(),
        "document_id": uuid4(),
        "chunk_index": 0,
        "content": "chunk content",
        "page_start": 1,
        "page_end": 1,
        "token_count": 10,
    }
    defaults.update(kwargs)
    return type("Chunk", (), defaults)()


def test_similarity_search_401_without_key(app_client):
    project_id = uuid4()
    response = app_client.post(
        f"/query/{project_id}",
        json={"query": "test", "top_k": 5},
    )
    assert response.status_code == 401


@patch("app.routers.query.query.execute_similarity_search", new_callable=AsyncMock)
def test_similarity_search_200_with_key_and_mocked_query(mock_search, app_client, fake_session, fake_api_key):
    mock_search.return_value = []
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.post(
            f"/query/{project_id}",
            json={"query": "test", "top_k": 5},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == str(project_id)
    assert data["query"] == "test"
    assert data["results"] == []
    assert data["total"] == 0


def test_list_documents_401_without_key(app_client):
    response = app_client.get(f"/query/{uuid4()}/documents")
    assert response.status_code == 401


@patch("app.routers.query.query.get_project_documents", new_callable=AsyncMock)
def test_list_documents_200_with_auth(mock_get_docs, app_client, fake_session, fake_api_key):
    doc = _fake_doc()
    mock_get_docs.return_value = [doc]
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.get(
            f"/query/{project_id}/documents",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "doc.pdf"


def test_get_document_401_without_key(app_client):
    response = app_client.get(f"/query/documents/{uuid4()}")
    assert response.status_code == 401


@patch("app.routers.query.query.get_document_by_id", new_callable=AsyncMock)
def test_get_document_404_when_missing(mock_get_doc, app_client, fake_session, fake_api_key):
    mock_get_doc.return_value = None
    document_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.get(
            f"/query/documents/{document_id}",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404


@patch("app.routers.query.query.get_document_by_id", new_callable=AsyncMock)
def test_get_document_200_when_found(mock_get_doc, app_client, fake_session, fake_api_key):
    doc = _fake_doc()
    mock_get_doc.return_value = doc
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.get(
            f"/query/documents/{doc.id}",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    assert response.json()["title"] == "doc.pdf"


def test_list_chunks_401_without_key(app_client):
    response = app_client.get(f"/query/documents/{uuid4()}/chunks")
    assert response.status_code == 401


@patch("app.routers.query.query.get_document_chunks", new_callable=AsyncMock)
def test_list_chunks_200_with_auth(mock_get_chunks, app_client, fake_session, fake_api_key):
    chunk = _fake_chunk()
    mock_get_chunks.return_value = [chunk]
    document_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.get(
            f"/query/documents/{document_id}/chunks",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "chunk content"


def test_delete_document_401_without_key(app_client):
    response = app_client.delete(f"/query/{uuid4()}/document?source=foo.pdf")
    assert response.status_code == 401


@patch("app.routers.query.query.delete_document_by_source", new_callable=AsyncMock)
def test_delete_document_404_for_unknown_source(mock_delete, app_client, fake_session, fake_api_key):
    mock_delete.return_value = 0
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.delete(
            f"/query/{project_id}/document?source=nonexistent.pdf",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 404


@patch("app.routers.query.query.delete_document_by_source", new_callable=AsyncMock)
def test_delete_document_200_when_deleted(mock_delete, app_client, fake_session, fake_api_key):
    mock_delete.return_value = 3
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.delete(
            f"/query/{project_id}/document?source=deleted.pdf",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Document deleted successfully."
    assert data["source_file"] == "deleted.pdf"
    assert data["chunks_deleted"] == 3


def test_stats_401_without_key(app_client):
    response = app_client.get(f"/query/{uuid4()}/stats")
    assert response.status_code == 401


@patch("app.routers.query.query.get_project_stats", new_callable=AsyncMock)
def test_stats_200_with_mocked_counts(mock_stats, app_client, fake_session, fake_api_key):
    mock_stats.return_value = {
        "total_chunks": 42,
        "total_sources": 5,
        "avg_chunk_length": 256.5,
        "min_chunk_length": 10,
        "max_chunk_length": 512,
    }
    project_id = uuid4()
    key = fake_api_key()

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(None),
    }):
        response = app_client.get(
            f"/query/{project_id}/stats",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["total_chunks"] == 42
    assert data["total_sources"] == 5
    assert data["avg_chunk_length"] == 256.5
    assert data["min_chunk_length"] == 10
    assert data["max_chunk_length"] == 512
