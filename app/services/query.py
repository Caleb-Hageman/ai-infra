from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk
from app.schemas.query import ChunkMatch

async def execute_similarity_search(
    session: AsyncSession,
    project_id: UUID,
    embedding: list[float],
    top_k: int
) -> list[ChunkMatch]:
    """Performs a vector similarity search using pgvector."""
    project_doc_ids = select(Document.id).where(Document.project_id == project_id)

    distance = DocumentChunk.embedding.cosine_distance(embedding)

    stmt = (
        select(DocumentChunk, distance.label("distance"))
        .where(
            DocumentChunk.document_id.in_(project_doc_ids),
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        ChunkMatch(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            score=round(1 - dist, 4),
        )
        for chunk, dist in rows
    ]


async def get_project_documents(session: AsyncSession, team_id: UUID, project_id: UUID):
    """Retrieves all documents for a specific project."""
    result = await session.execute(
        select(Document).where(
            Document.team_id == team_id, Document.project_id == project_id
        )
    )
    return result.scalars().all()


async def get_document_by_id(session: AsyncSession, document_id: UUID):
    """Retrieves a single document by its ID."""
    return await session.get(Document, document_id)


async def get_document_chunks(session: AsyncSession, document_id: UUID):
    """Retrieves all chunks associated with a specific document."""
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return result.scalars().all()