from uuid import UUID
from pydantic import BaseModel

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