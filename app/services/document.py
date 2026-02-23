from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk, DocumentSourceType, IngestionJob
from app.schemas.document import IngestRequest

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

    for chunk in body.chunks:
        session.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=chunk.embedding,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                token_count=chunk.token_count,
            )
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