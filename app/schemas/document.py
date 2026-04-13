from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InitUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str | None = None


class InitUploadResponse(BaseModel):
    upload_url: str
    session_id: UUID
    expires_in_seconds: int
    gcs_path: str


class IngestionJobOut(BaseModel):
    id: UUID
    status: str
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    chunks_created: int | None
    total_chunks: int | None
    embedding_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: UUID
    team_id: UUID
    project_id: UUID
    title: str | None
    source_type: str
    gcs_uri: str | None
    status: str
    ingestion_progress_percent: int = 0
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
    latest_ingestion_job: IngestionJobOut | None = None

    model_config = {"from_attributes": True}


class ChunkOut(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    token_count: int | None

    model_config = {"from_attributes": True}