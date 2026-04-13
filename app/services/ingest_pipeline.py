# Purpose: Chunking, embedding, and indexing for documents stored in GCS (async ingest path).

import logging
import os
import tempfile
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM
from app.models import Document, DocumentStatus, IngestionJob
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

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        gcs.download_blob_to_path(gcs_path, tmp_path)

        text = rag_service.extract_text(tmp_path)
        chunks = rag_service.chunk_text(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        await rag_service.ensure_dimension(EMBEDDING_DIM)
        vectors = await rag_service.embed_documents([chunk["content"] for chunk in chunks])

        chunk_payload = []
        for chunk, vector in zip(chunks, vectors):
            item = dict(chunk)
            item["embedding"] = vector
            chunk_payload.append(item)

        await insert_document_chunks(
            session, document_id=doc.id, chunks=chunk_payload, commit=False
        )
        session.add(IngestionJob(document_id=doc.id, chunks_created=len(chunk_payload)))
        doc.status = DocumentStatus.ready
        await session.commit()
        await session.refresh(doc)
    except ValueError as e:
        await session.rollback()
        doc = await session.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.failed
            await session.commit()
        logger.warning("Ingestion validation failed: %s", e)
    except Exception as e:
        await session.rollback()
        doc = await session.get(Document, document_id)
        if doc:
            doc.status = DocumentStatus.failed
            await session.commit()
        logger.exception("Ingestion failed: %s", e)
