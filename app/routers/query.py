from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey, Document, DocumentChunk

router = APIRouter(prefix="/query", tags=["query"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class QueryRequest(BaseModel):
    embedding: list[float]
    top_k: int = 5


class ChunkMatch(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    score: float

    model_config = {"from_attributes": True}


class QueryResponse(BaseModel):
    project_id: UUID
    results: list[ChunkMatch]


# ── Similarity search via pgvector ───────────────────────────────────────────


@router.post("/{project_id}", response_model=QueryResponse)
async def similarity_search(
    project_id: UUID,
    body: QueryRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if len(body.embedding) != 1536:
        raise HTTPException(
            422, f"Embedding must be 1536 dimensions, got {len(body.embedding)}"
        )

    project_doc_ids = select(Document.id).where(Document.project_id == project_id)

    distance = DocumentChunk.embedding.cosine_distance(body.embedding)

    stmt = (
        select(DocumentChunk, distance.label("distance"))
        .where(
            DocumentChunk.document_id.in_(project_doc_ids),
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(body.top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    matches = [
        ChunkMatch(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            score=round(1 - dist, 4),
        )
        for chunk, dist in rows
    ]

    return QueryResponse(project_id=project_id, results=matches)
