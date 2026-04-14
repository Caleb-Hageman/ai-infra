import hashlib
import os
from fastapi import Request, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.db import get_session
from app.models import ApiKey, ApiKeyStatus

ADMIN_ID = UUID(os.getenv("ADMIN_TEAM_ID", "00000000-0000-0000-0000-000000000000"))


bearer_scheme = HTTPBearer()

async def get_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    """Validate a Bearer token and return the active ApiKey row."""
    token = credentials.credentials
    key_hash = hashlib.sha256(token.encode()).hexdigest()

    result = await session.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    request.state.api_key_id = api_key.id
    request.state.team_id = api_key.team_id

    return api_key
