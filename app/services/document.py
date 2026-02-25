from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk, DocumentSourceType, IngestionJob
from app.schemas.document import IngestRequest

from app.services import insert

async def create_uploaded_document(
    session: AsyncSession, 
    team_id: UUID, 
    project_id: UUID, 
    filename: str, 
    gcs_path: str,
    mime_type: str,
) -> Document:
    doc = Document(
        team_id=team_id,
        project_id=project_id,
        title=filename,
        source_type=DocumentSourceType.upload,
        gcs_uri=gcs_path,
        mime_type=mime_type,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def process_manual_chunks(
    session: AsyncSession,
    team_id: UUID,
    project_id: UUID,
    body: IngestRequest,
) -> Document:
    doc = Document(
        team_id=team_id,
        project_id=project_id,
        title=body.title,
        source_type=DocumentSourceType.manual,
    )
    session.add(doc)
    await session.flush()

    chunk_payload = [
        {
            "chunk_index": c.chunk_index,
            "content": c.content,
            "embedding": c.embedding,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "token_count": c.token_count,
        }
        for c in body.chunks
    ]

    await insert.insert_document_chunks(
        session,
        document_id=doc.id,
        chunks=chunk_payload,
        commit=False
    )

    job = IngestionJob(
        document_id=doc.id,
        chunks_created=len(body.chunks),
    )
    session.add(job)

    doc.status = "ready" if all(c.embedding for c in body.chunks) else "processing"
    await session.commit()
    await session.refresh(doc)
    return doc