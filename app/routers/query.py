from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class PromptRequest(BaseModel):
    message: str


@router.post("/query")
def create_prompt(prompt: PromptRequest):
    return {"message": prompt.message}
