# Purpose: Async ingest pipeline process_uploaded_document.

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import DocumentStatus, IngestionStatus
from app.services.ingest_pipeline import process_uploaded_document


@pytest.mark.asyncio
async def test_process_uploaded_document_returns_when_document_missing():
    session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    await process_uploaded_document(
        session,
        document_id=uuid4(),
        gcs_path="gcs/path",
        suffix=".txt",
        chunk_size=256,
        chunk_overlap=50,
    )

    session.execute.assert_called_once()


def _make_job_mock():
    job = MagicMock()
    job.id = uuid4()
    job.created_at = datetime.now(timezone.utc)
    return job


@pytest.mark.asyncio
async def test_process_uploaded_document_happy_path():
    from app.config import EMBEDDING_DIM

    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    added = []
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock(side_effect=added.append)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.flush = AsyncMock()

    with (
        patch("app.services.ingest_pipeline.gcs.download_blob_to_path") as mock_dl,
        patch(
            "app.services.ingest_pipeline.rag_service.extract_text",
            return_value="full text",
        ),
        patch(
            "app.services.ingest_pipeline.rag_service.chunk_text",
            return_value=[
                {"chunk_index": 0, "content": "a"},
                {"chunk_index": 1, "content": "b"},
            ],
        ),
        patch(
            "app.services.ingest_pipeline.rag_service.ensure_dimension",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.ingest_pipeline.rag_service.embed_documents",
            new_callable=AsyncMock,
            return_value=[[0.1] * EMBEDDING_DIM, [0.1] * EMBEDDING_DIM],
        ),
        patch(
            "app.services.ingest_pipeline.insert_document_chunks",
            new_callable=AsyncMock,
        ),
    ):
        await process_uploaded_document(
            session,
            document_id=doc_id,
            gcs_path="gcs/path",
            suffix=".txt",
            chunk_size=256,
            chunk_overlap=50,
        )

    mock_dl.assert_called_once()
    job = added[0]
    assert job.total_chunks == 2
    assert job.chunks_created == 2
    assert job.status == IngestionStatus.succeeded
    assert session.commit.call_count >= 3
    assert doc.status == DocumentStatus.ready


@pytest.mark.asyncio
async def test_process_uploaded_document_value_error_marks_failed():
    from app.config import EMBEDDING_DIM

    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    job_mock = _make_job_mock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, id: doc if model.__name__ == "Document" else job_mock)

    with (
        patch("app.services.ingest_pipeline.gcs.download_blob_to_path"),
        patch("app.services.ingest_pipeline.rag_service.extract_text", return_value="x"),
        patch(
            "app.services.ingest_pipeline.rag_service.chunk_text",
            return_value=[{"chunk_index": 0, "content": "c"}],
        ),
        patch(
            "app.services.ingest_pipeline.rag_service.ensure_dimension",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.ingest_pipeline.rag_service.embed_documents",
            new_callable=AsyncMock,
            return_value=[[0.1] * EMBEDDING_DIM],
        ),
        patch(
            "app.services.ingest_pipeline.insert_document_chunks",
            new_callable=AsyncMock,
            side_effect=ValueError("validation"),
        ),
    ):
        await process_uploaded_document(
            session,
            document_id=doc_id,
            gcs_path="gcs/path",
            suffix=".txt",
            chunk_size=256,
            chunk_overlap=50,
        )

    session.rollback.assert_called()
    session.get.assert_called()
    assert doc.status == DocumentStatus.failed
    assert job_mock.status == IngestionStatus.failed
    assert job_mock.error_message == "validation"


@pytest.mark.asyncio
async def test_process_uploaded_document_generic_exception_marks_failed():
    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    job_mock = _make_job_mock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.get = AsyncMock(side_effect=lambda model, id: doc if model.__name__ == "Document" else job_mock)

    with (
        patch(
            "app.services.ingest_pipeline.gcs.download_blob_to_path",
            side_effect=RuntimeError("network"),
        ),
    ):
        await process_uploaded_document(
            session,
            document_id=doc_id,
            gcs_path="gcs/path",
            suffix=".txt",
            chunk_size=256,
            chunk_overlap=50,
        )

    session.rollback.assert_called()
    assert doc.status == DocumentStatus.failed
    assert job_mock.status == IngestionStatus.failed
    assert job_mock.error_message == "network"
