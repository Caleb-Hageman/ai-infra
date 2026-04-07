from uuid import UUID
from pydantic import BaseModel, Field

class Citation(BaseModel):
    source: str
    content: str
    url: str | None = None
    score: float

class ChatRequest(BaseModel):
    question: str
    project_id: UUID | None = None
    system_prompt: str | None = None
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)

class ChatResponse(BaseModel):
    status: str
    answer: str
    citations: list[Citation]
