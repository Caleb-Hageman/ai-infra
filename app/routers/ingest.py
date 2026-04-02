# Purpose: Ingest routes — signed PUT to GCS, then complete triggers async chunk/embed/index.

import logging
import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.config import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    SIGNED_PUT_EXPIRATION_MINUTES,
)
from app.db import async_session, get_session
from app.models import ApiKey, Document, DocumentChunk, DocumentStatus, Project, UploadSession
from app.schemas.document import DocumentOut, InitUploadRequest, InitUploadResponse
from app.services import gcs
from app.services.document import create_uploaded_document
from app.services.ingest_pipeline import process_uploaded_document
from app.services.rag import rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


async def _background_ingest(
    document_id: UUID,
    gcs_path: str,
    suffix: str,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    try:
        async with async_session() as session:
            await process_uploaded_document(
                session,
                document_id=document_id,
                gcs_path=gcs_path,
                suffix=suffix,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
    except Exception:
        logger.exception("Background ingest failed for document %s", document_id)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    if not base or ".." in base or base.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base


def _resolved_content_type(filename: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


@router.post("/{project_id}/upload", response_model=InitUploadResponse)
async def init_upload(
    project_id: UUID,
    body: InitUploadRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id
    allowed = {".pdf", ".txt", ".md", ".markdown"}
    suffix = Path(body.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(allowed)}",
        )

    filename = _safe_filename(body.filename)
    stmt = select(Project).where(
        Project.id == project_id,
        Project.team_id == team_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")

    content_type = _resolved_content_type(filename, body.content_type)
    gcs_path = f"{team_id}/{project_id}/{uuid4()}_{filename}"

    try:
        upload_url = gcs.generate_signed_put_url(gcs_path, content_type=content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=SIGNED_PUT_EXPIRATION_MINUTES)
    upload_session = UploadSession(
        team_id=team_id,
        project_id=project_id,
        gcs_path=gcs_path,
        filename=filename,
        mime_type=content_type,
        expires_at=expires_at,
    )
    session.add(upload_session)
    await session.commit()
    await session.refresh(upload_session)

    return InitUploadResponse(
        upload_url=upload_url,
        session_id=upload_session.id,
        expires_in_seconds=SIGNED_PUT_EXPIRATION_MINUTES * 60,
        gcs_path=gcs_path,
    )


@router.post(
    "/{project_id}/upload/{session_id}/complete",
    response_model=DocumentOut,
    status_code=202,
)
async def complete_upload(
    project_id: UUID,
    session_id: UUID,
    background_tasks: BackgroundTasks,
    chunk_size: int = Query(DEFAULT_CHUNK_SIZE, ge=100, le=512),
    chunk_overlap: int = Query(DEFAULT_CHUNK_OVERLAP, ge=0, le=1000),
    current_key: ApiKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id
    stmt = select(UploadSession).where(
        UploadSession.id == session_id,
        UploadSession.team_id == team_id,
        UploadSession.project_id == project_id,
    )
    result = await db.execute(stmt)
    us = result.scalar_one_or_none()
    if not us:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if us.completed_at is not None:
        raise HTTPException(status_code=409, detail="Upload session already completed")
    now = datetime.now(timezone.utc)
    exp = us.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now > exp:
        raise HTTPException(status_code=410, detail="Upload session expired")

    try:
        gcs.verify_uploaded_blob_size(us.gcs_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Object not found in GCS; PUT the file to upload_url first",
        ) from None
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e

    suffix = Path(us.filename).suffix.lower() or ".bin"
    doc = await create_uploaded_document(
        session=db,
        team_id=team_id,
        project_id=project_id,
        filename=us.filename,
        gcs_path=us.gcs_path,
        mime_type=us.mime_type,
        status=DocumentStatus.processing,
        commit=False,
    )
    us.document_id = doc.id
    us.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(
        _background_ingest,
        doc.id,
        us.gcs_path,
        suffix,
        chunk_size,
        chunk_overlap,
    )

    return doc


@router.post("/{project_id}/repair-embeddings", status_code=200)
async def repair_embeddings(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_key: ApiKey = Depends(get_api_key),
):
    stmt = (
        select(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.id == project_id,
            Project.team_id == current_key.team_id,
            DocumentChunk.embedding.is_(None),
        )
    )

    result = await session.execute(stmt)
    chunks = result.scalars().all()

    if not chunks:
        return {"message": "No NULL embeddings found for this project."}

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.content for c in batch]

        vectors = await rag_service.embed_documents(texts)

        for chunk, vector in zip(batch, vectors):
            chunk.embedding = vector

        await session.commit()

    return {"message": f"Successfully updated {len(chunks)} chunks for project {project_id}."}
