from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey, Project
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat as chat_service

router = APIRouter(prefix="/api/v1", tags=["chat"])

@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if body.project_id:
        project = await session.get(Project, body.project_id)
        if not project:
            raise HTTPException(404)
        if project.team_id != current_key.team_id:
            raise HTTPException(403)
    try:
        answer, citations = await chat_service.generate_response(
            session,
            current_key.team_id,
            body.project_id,
            body.question,
            body.system_prompt,
            body.min_score,
        )
    except RuntimeError:
        raise HTTPException(500)
    return ChatResponse(status="success", answer=answer, citations=citations)
