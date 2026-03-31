from uuid import UUID
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, EMBEDDING_DIM
from app.db import get_session
from app.models import ApiKey, IngestionJob, DocumentChunk, Document, Project

from sqlalchemy import select

from app.schemas.document import DocumentOut
from app.services import gcs, document
from app.services.insert import insert_document_chunks
from app.services.rag import rag_service

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/{project_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_file(
    project_id: UUID,
    file: UploadFile,
    chunk_size: int = Query(DEFAULT_CHUNK_SIZE, ge=100, le=512),
    chunk_overlap: int = Query(DEFAULT_CHUNK_OVERLAP, ge=0, le=1000),
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_id = current_key.team_id
    allowed = {".pdf", ".txt", ".md", ".markdown"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(allowed)}",
        )

    try:
        destination = f"{team_id}/{project_id}/{file.filename}"
        gcs_path = gcs.upload_file_stream(file.file, destination)
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

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file.file.seek(0)
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        text = rag_service.extract_text(tmp_path)
        chunks = rag_service.chunk_text(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        await rag_service.ensure_dimension(EMBEDDING_DIM)
        vectors = await rag_service.embed_documents([chunk["content"] for chunk in chunks])

        chunk_payload = []
        for chunk, vector in zip(chunks, vectors):
            item = dict(chunk)
            item["embedding"] = vector
            chunk_payload.append(item)

        await insert_document_chunks(
            session, document_id=doc.id, chunks=chunk_payload, commit=False
        )
        session.add(IngestionJob(document_id=doc.id, chunks_created=len(chunk_payload)))
        doc.status = "ready"
        await session.commit()
        await session.refresh(doc)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        doc.status = "failed"
        await session.commit()
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")
    finally:
        os.unlink(tmp_path)

    return doc

@router.post("/{project_id}/repair-embeddings", status_code=200)
async def repair_embeddings(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    current_key: ApiKey = Depends(get_api_key)
):
    # 1. Securely fetch ONLY chunks belonging to this project and this team
    stmt = (
        select(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.id == project_id,
            Project.team_id == current_key.team_id,
            DocumentChunk.embedding == None
        )
    )
    
    result = await session.execute(stmt)
    chunks = result.scalars().all()
    
    if not chunks:
        return {"message": "No NULL embeddings found for this project."}

    # 2. Batch process to avoid Cloud Run memory/timeout limits
    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.content for c in batch]
        
        # This calls your mxbai-embed-large-v1 (1024 dims)
        vectors = await rag_service.embed_documents(texts)
        
        for chunk, vector in zip(batch, vectors):
            chunk.embedding = vector
            
        await session.commit()
    
    return {"message": f"Successfully updated {len(chunks)} chunks for project {project_id}."}