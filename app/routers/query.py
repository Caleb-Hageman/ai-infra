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
from app.services import gcs


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

@router.get("/documents/{document_id}/test-url")
async def test_document_signed_url(
    document_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    """
    Test endpoint to verify GCS signed URL generation for a specific document.
    Replicates the logic used in the Chat Citation loop.
    """
    # 1. Fetch the document using your existing query service
    doc = await query.get_document_by_id(session, document_id)
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in database")

    # 2. Verify it has a GCS URI
    if not doc.gcs_uri:
        raise HTTPException(
            status_code=400, 
            detail="Document record exists but has no gcs_uri"
        )

    # 3. Call your updated generate_signed_url function
    # This will use the SA_EMAIL and handle the URI/Blob Name logic we fixed
    try:
        signed_url = gcs.generate_signed_url(doc.gcs_uri)
        
        if not signed_url:
            return {
                "status": "error",
                "message": "generate_signed_url returned None. Check if file exists in GCS.",
                "database_uri": doc.gcs_uri
            }

        return {
            "status": "success",
            "document_title": doc.title,
            "database_uri": doc.gcs_uri,
            "presigned_url": signed_url
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"URL Generation crashed: {str(e)}"
        )