# Purpose: Query service unit tests (execute_similarity_search with mocked session).

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.config import EMBEDDING_DIM
from app.models import DocumentStatus, IngestionStatus
from app.services.query import (
    _document_out,
    execute_similarity_search,
    execute_similarity_search_for_source,
    execute_similarity_search_for_team,
)


def _fake_chunk_row(content: str = "chunk content", score: float = 0.95):
    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.document_id = uuid4()
    chunk.chunk_index = 0
    chunk.content = content
    return chunk, "doc.pdf", "gs://bucket/doc.pdf", 1 - score


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_returns_chunk_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * EMBEDDING_DIM

    project_id = uuid4()
    row = _fake_chunk_row("hello world", 0.92)
    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search(session, project_id, "query", top_k=5)

    assert len(matches) == 1
    assert matches[0].content == "hello world"
    assert matches[0].score == 0.92
    assert matches[0].source_file == "doc.pdf"
    assert matches[0].chunk_length == 11
    mock_ensure.assert_called_once_with(EMBEDDING_DIM)
    mock_embed.assert_called_once_with("query")
    session.execute.assert_called_once()


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_for_team_returns_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * EMBEDDING_DIM
    team_id = uuid4()
    row = _fake_chunk_row("team chunk", 0.88)
    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search_for_team(
        session, team_id, "query", top_k=3
    )

    assert len(matches) == 1
    assert matches[0].content == "team chunk"
    assert matches[0].score == 0.88
    session.execute.assert_called_once()


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_for_source_returns_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * EMBEDDING_DIM
    project_id = uuid4()
    row = _fake_chunk_row("source chunk", 0.91)
    mock_result = MagicMock()
    mock_result.all.return_value = [row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search_for_source(
        session, project_id, "query", top_k=5, source_filter="doc.pdf"
    )

    assert len(matches) == 1
    assert matches[0].content == "source chunk"
    session.execute.assert_called_once()


def _fake_doc_for_progress(**kwargs):
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "team_id": uuid4(),
        "project_id": uuid4(),
        "title": "doc.txt",
        "source_type": "upload",
        "gcs_uri": "gs://bucket/doc.txt",
        "status": DocumentStatus.processing,
        "created_at": now,
        "updated_at": now,
        "ingestion_jobs": [],
    }
    defaults.update(kwargs)
    return type("Document", (), defaults)()


def _fake_job(**kwargs):
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "status": IngestionStatus.running,
        "error_message": None,
        "started_at": now,
        "finished_at": None,
        "chunks_created": 0,
        "total_chunks": None,
        "embedding_model": "text-embedding",
        "created_at": now,
    }
    defaults.update(kwargs)
    return type("IngestionJob", (), defaults)()


def test_build_document_out_reports_processing_progress():
    job = _fake_job(
        status=IngestionStatus.running,
        chunks_created=2,
        total_chunks=4,
    )
    doc = _fake_doc_for_progress(ingestion_jobs=[job])

    result = _document_out(doc, chunk_count=2)

    assert result.ingestion_progress_percent == 50
    assert result.chunk_count == 2
    assert result.latest_ingestion_job is not None
    assert result.latest_ingestion_job.status == "running"


def test_build_document_out_reports_ready_progress():
    finished_at = datetime.now(timezone.utc)
    job = _fake_job(
        status=IngestionStatus.succeeded,
        finished_at=finished_at,
        chunks_created=3,
        total_chunks=3,
    )
    doc = _fake_doc_for_progress(
        status=DocumentStatus.ready,
        ingestion_jobs=[job],
    )

    result = _document_out(doc, chunk_count=3)

    assert result.ingestion_progress_percent == 100
    assert result.chunk_count == 3
    assert result.latest_ingestion_job is not None
    assert result.latest_ingestion_job.status == "succeeded"
