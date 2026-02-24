from uuid import UUID
from pydantic import BaseModel

class QueryRequest(BaseModel):
    embedding: list[float]
    top_k: int = 5


class ChunkMatch(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    score: float

    model_config = {"from_attributes": True}


class QueryResponse(BaseModel):
    project_id: UUID
    results: list[ChunkMatch]