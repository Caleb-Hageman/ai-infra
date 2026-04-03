import logging

import redis.exceptions as redis_exc
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey, Project
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat as chat_service
from app.services.redis_service import rate_limiter

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    team_limits = [
        (21, 60),      # 21 requests per minute
        (100, 3600),  # 100 requests per hour
        (500, 86400) # 500 requests per day
    ]

    try:
        is_limited = await rate_limiter.is_rate_limited(
            team_id=str(current_key.team_id),
            limits=team_limits,
        )
    except redis_exc.RedisError as e:
        logger.exception("Redis unavailable for rate limiting")
        raise HTTPException(
            status_code=503,
            detail="Rate limiting backend unavailable",
        ) from e

    if is_limited:
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded for one of your time windows (Min/Hour/Day)."
        )

    if body.project_id:
        project = await session.get(Project, body.project_id)
        if not project:
            raise HTTPException(404)
        if project.team_id != current_key.team_id:
            raise HTTPException(403)
    try:
        answer, citations = await chat_service.generate_response(
            session, current_key.team_id, body.project_id, body.question, body.system_prompt
        )
    except RuntimeError:
        raise HTTPException(500)
    return ChatResponse(status="success", answer=answer, citations=citations)
