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


class ChunkOut(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    page_start: int | None
    page_end: int | None
    token_count: int | None

    model_config = {"from_attributes": True}