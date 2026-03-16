from uuid import UUID
from pydantic import BaseModel

class ChatRequest(BaseModel):
    question: str
    project_id: UUID | None = None
    system_prompt: str | None = None

class ChatResponse(BaseModel):
    status: str
    answer: str
    citations: list
