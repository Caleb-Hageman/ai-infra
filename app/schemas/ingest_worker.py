# Purpose: Request body for POST /ingest-worker (Cloud Tasks HTTP target).

from uuid import UUID

from pydantic import BaseModel, Field

from app.config import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE


class IngestWorkerRequest(BaseModel):
    document_id: UUID
    gcs_path: str
    suffix: str
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=100, le=512)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=1000)
