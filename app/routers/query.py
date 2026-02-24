from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey

from app.schemas.query import QueryRequest, QueryResponse
from app.schemas.document import DocumentOut, ChunkOut
from app.services import query

router = APIRouter(prefix="/query", tags=["query"])


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
    
    matches = await query.execute_similarity_search(
        session=session,
        project_id=project_id,
        embedding=body.embedding,
        top_k=body.top_k
    )

    return QueryResponse(project_id=project_id, results=matches)

@router.get("/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id
        
    return await query.get_project_documents(session, team_id, project_id)

@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    doc = await query.get_document_by_id(session, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc

@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    document_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    return await query.get_document_chunks(session, document_id)