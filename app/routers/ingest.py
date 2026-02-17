from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey, Document, DocumentChunk, DocumentSourceType, IngestionJob

router = APIRouter(prefix="/ingest", tags=["ingest"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class DocumentOut(BaseModel):
    id: UUID
    team_id: UUID
    project_id: UUID
    title: str | None
    source_type: str
    gcs_uri: str | None
    status: str

    model_config = {"from_attributes": True}


class ChunkCreate(BaseModel):
    content: str
    embedding: list[float] | None = None
    chunk_index: int
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None


class IngestRequest(BaseModel):
    title: str
    chunks: list[ChunkCreate]


class ChunkOut(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    token_count: int | None

    model_config = {"from_attributes": True}


# ── Upload file to GCS + create Document record ─────────────────────────────
# This endpoint bridges YOUR work (Postgres) with your TEAMMATE's (GCS).
# It stores the raw file in GCS and creates a tracking row in Postgres.


@router.post("/{team_id}/{project_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_file(
    team_id: UUID,
    project_id: UUID,
    file: UploadFile,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")
    try:
        from app.services import gcs

        destination = f"{team_id}/{file.filename}"
        gcs_path = gcs.upload_file_stream(file.file, destination, file.content_type)
    except Exception as e:
        raise HTTPException(500, f"GCS upload failed: {e}")

    doc = Document(
        team_id=team_id,
        project_id=project_id,
        title=file.filename,
        source_type=DocumentSourceType.upload,
        gcs_uri=gcs_path,
        mime_type=file.content_type,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


# ── Push chunks + embeddings directly into Postgres / pgvector ───────────────
# This is YOUR core endpoint. No GCS involved.


@router.post("/{team_id}/{project_id}/chunks", response_model=DocumentOut, status_code=201)
async def ingest_chunks(
    team_id: UUID,
    project_id: UUID,
    body: IngestRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")
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


# ── Read endpoints ───────────────────────────────────────────────────────────


@router.get("/{team_id}/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    team_id: UUID,
    project_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")
    result = await session.execute(
        select(Document).where(
            Document.team_id == team_id, Document.project_id == project_id
        )
    )
    return result.scalars().all()


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    doc = await session.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    document_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return result.scalars().all()
