from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey

from app.schemas.document import DocumentOut, IngestRequest
from app.services import gcs, document

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/{project_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_file(
    project_id: UUID,
    file: UploadFile,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id
    
    try:
        destination = f"{team_id}/{project_id}/{file.filename}"
        gcs_path = gcs.upload_file_stream(file.file, destination, file.content_type)
    except Exception as e:
        raise HTTPException(500, f"GCS upload failed: {e}")

    doc = await document.create_uploaded_document(
        session=session,
        team_id=team_id,
        project_id=project_id,
        filename=file.filename,
        gcs_path=gcs_path,
        mime_type=file.content_type,
    )
    return doc


@router.post("/{team_id}/{project_id}/chunks", response_model=DocumentOut, status_code=201)
async def ingest_chunks(
    project_id: UUID,
    body: IngestRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id

    doc = await document.process_manual_chunks(
        session=session,
        team_id=team_id,
        project_id=project_id,
        body=body,
    )
    return doc