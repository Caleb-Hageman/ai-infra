from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey

from app.schemas.query import (
    DeleteResponse,
    QueryRequest,
    QueryResponse,
    StatsResponse,
)
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
    try:
        if body.source:
            matches = await query.execute_similarity_search_for_source(
                session=session,
                project_id=project_id,
                query_text=body.query,
                top_k=body.top_k,
                source_filter=body.source,
            )
        else:
            matches = await query.execute_similarity_search(
                session=session,
                project_id=project_id,
                query_text=body.query,
                top_k=body.top_k,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return QueryResponse(
        project_id=project_id,
        query=body.query,
        results=matches,
        total=len(matches),
    )

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


@router.get("/{project_id}/stats", response_model=StatsResponse)
async def stats(
    project_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    return await query.get_project_stats(session, current_key.team_id, project_id)


@router.delete("/{project_id}/document", response_model=DeleteResponse)
async def delete_document(
    project_id: UUID,
    source: str = Query(..., description="Exact source filename to delete"),
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    deleted = await query.delete_document_by_source(
        session, current_key.team_id, project_id, source
    )
    if deleted == 0:
        raise HTTPException(status_code=404, detail=f"No chunks found for '{source}'.")
    return DeleteResponse(
        message="Document deleted successfully.",
        source_file=source,
        chunks_deleted=deleted,
    )
