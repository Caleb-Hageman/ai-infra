# Purpose: Chunking, embedding, and indexing for documents stored in GCS (async ingest path).

import logging
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM, EMBEDDING_MODEL
from app.models import Document, DocumentStatus, IngestionJob, IngestionStatus
from app.services import gcs
from app.services.insert import insert_document_chunks
from app.services.rag import rag_service

logger = logging.getLogger(__name__)


async def process_uploaded_document(
    session: AsyncSession,
    *,
    document_id: UUID,
    gcs_path: str,
    suffix: str,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    stmt = select(Document).where(Document.id == document_id)
    result = await session.execute(stmt)
    doc = result.scalar_one_or_none()
    if not doc:
        logger.error("process_uploaded_document: document %s not found", document_id)
        return

    job = IngestionJob(
        document_id=document_id,
        status=IngestionStatus.running,
        started_at=datetime.now(timezone.utc),
        embedding_model=EMBEDDING_MODEL,
    )
    session.add(job)
    await session.commit()
    job_id = job.id

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        gcs.download_blob_to_path(gcs_path, tmp_path)

        text = rag_service.extract_text(tmp_path)
        chunks = rag_service.chunk_text(
            text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        await rag_service.ensure_dimension(EMBEDDING_DIM)
        job.total_chunks = len(chunks)
        job.chunks_created = 0
        await session.commit()

        batch_size = 50
        for index in range(0, len(chunks), batch_size):
            batch = chunks[index : index + batch_size]
            vectors = await rag_service.embed_documents(
                [chunk["content"] for chunk in batch]
            )
            payload = []
            for chunk, vector in zip(batch, vectors):
                item = dict(chunk)
                item["embedding"] = vector
                payload.append(item)
            await insert_document_chunks(
                session, document_id=doc.id, chunks=payload, commit=False
            )
            job.chunks_created = index + len(payload)
            await session.commit()

        job.status = IngestionStatus.succeeded
        job.finished_at = datetime.now(timezone.utc)
        doc.status = DocumentStatus.ready
        await session.commit()
    except ValueError as e:
        await session.rollback()
        await _mark_failed(session, document_id, job_id, str(e))
        logger.warning("Ingestion validation failed: %s", e)
    except Exception as e:
        await session.rollback()
        await _mark_failed(session, document_id, job_id, str(e))
        logger.exception("Ingestion failed: %s", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _mark_failed(
    session: AsyncSession,
    document_id: UUID,
    job_id: UUID,
    error_message: str,
) -> None:
    doc = await session.get(Document, document_id)
    job = await session.get(IngestionJob, job_id)
    if doc:
        doc.status = DocumentStatus.failed
    if job:
        job.status = IngestionStatus.failed
        job.finished_at = datetime.now(timezone.utc)
        job.error_message = error_message
    await session.commit()
