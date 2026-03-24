from uuid import UUID
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import EMBEDDING_DIM
from app.models import Document, DocumentChunk
from app.schemas.query import ChunkMatch
from app.services.rag import rag_service

async def execute_similarity_search(
    session: AsyncSession,
    project_id: UUID,
    query_text: str,
    top_k: int
) -> list[ChunkMatch]:
    """Performs a vector similarity search using pgvector."""
    await rag_service.ensure_dimension(EMBEDDING_DIM)
    query_embedding = await rag_service.embed_query(query_text)
    project_doc_ids = select(Document.id).where(Document.project_id == project_id)

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(DocumentChunk, Document.title, Document.gcs_uri, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
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
            source_file=source_file,
            gcs_uri=gcs_uri,
            chunk_length=len(chunk.content),
        )
        for chunk, source_file, gcs_uri, dist in rows
    ]


async def execute_similarity_search_for_team(
    session: AsyncSession,
    team_id: UUID,
    query_text: str,
    top_k: int,
) -> list[ChunkMatch]:
    """Similarity search across all documents for a team."""
    await rag_service.ensure_dimension(1536)
    query_embedding = await rag_service.embed_query(query_text)
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(DocumentChunk, Document.title, Document.gcs_uri, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.team_id == team_id,
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
            source_file=source_file,
            gcs_uri=gcs_uri,
            chunk_length=len(chunk.content),
        )
        for chunk, source_file, gcs_uri, dist in rows
    ]


async def execute_similarity_search_for_source(
    session: AsyncSession,
    project_id: UUID,
    query_text: str,
    top_k: int,
    source_filter: str,
) -> list[ChunkMatch]:
    """Similarity search scoped to one source filename."""
    await rag_service.ensure_dimension(EMBEDDING_DIM)
    query_embedding = await rag_service.embed_query(query_text)
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)

    stmt = (
        select(DocumentChunk, Document.title, Document.gcs_uri, distance.label("distance"))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.project_id == project_id,
            Document.title == source_filter,
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
            source_file=source_file,
            gcs_uri=gcs_uri,
            chunk_length=len(chunk.content),
        )
        for chunk, source_file, gcs_uri, dist in rows
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


async def get_project_stats(session: AsyncSession, team_id: UUID, project_id: UUID) -> dict:
    stmt = (
        select(
            func.count(DocumentChunk.id),
            func.count(func.distinct(Document.id)),
            func.avg(func.length(DocumentChunk.content)),
            func.min(func.length(DocumentChunk.content)),
            func.max(func.length(DocumentChunk.content)),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.team_id == team_id, Document.project_id == project_id)
    )
    row = (await session.execute(stmt)).one()
    return {
        "total_chunks": row[0] or 0,
        "total_sources": row[1] or 0,
        "avg_chunk_length": float(row[2]) if row[2] else 0.0,
        "min_chunk_length": row[3] or 0,
        "max_chunk_length": row[4] or 0,
    }


async def delete_document_by_source(
    session: AsyncSession, team_id: UUID, project_id: UUID, source: str
) -> int:
    doc_result = await session.execute(
        select(Document.id).where(
            Document.team_id == team_id,
            Document.project_id == project_id,
            Document.title == source,
        )
    )
    doc_ids = [row[0] for row in doc_result.all()]
    if not doc_ids:
        return 0

    chunk_delete = await session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id.in_(doc_ids))
    )
    await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
    await session.commit()
    return int(chunk_delete.rowcount or 0)