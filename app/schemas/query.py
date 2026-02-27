from uuid import UUID
from pydantic import BaseModel, Field
from typing import Optional

class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    source: Optional[str] = None


class ChunkMatch(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    score: float
    source_file: str | None
    chunk_length: int

    model_config = {"from_attributes": True}


class QueryResponse(BaseModel):
    project_id: UUID
    query: str
    results: list[ChunkMatch]
    total: int


class StatsResponse(BaseModel):
    total_chunks: int
    total_sources: int
    avg_chunk_length: float
    min_chunk_length: int
    max_chunk_length: int


class DeleteResponse(BaseModel):
    message: str
    source_file: str
    chunks_deleted: int