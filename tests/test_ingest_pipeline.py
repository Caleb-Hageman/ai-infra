# Purpose: Async ingest pipeline process_uploaded_document.

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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


@pytest.mark.asyncio
async def test_process_uploaded_document_happy_path():
    from app.config import EMBEDDING_DIM

    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    with (
        patch("app.services.ingest_pipeline.gcs.download_blob_to_path") as mock_dl,
        patch(
            "app.services.ingest_pipeline.rag_service.extract_text",
            return_value="full text",
        ),
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
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_process_uploaded_document_value_error_marks_failed():
    from app.config import EMBEDDING_DIM

    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=doc)

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


@pytest.mark.asyncio
async def test_process_uploaded_document_generic_exception_marks_failed():
    doc_id = uuid4()
    doc = MagicMock()
    doc.id = doc_id

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = doc
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=doc)

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
