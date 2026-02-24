import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_api_key
from app.db import get_session
from app.models import ApiKey, ApiKeyStatus, Project, Team

router = APIRouter(prefix="/teams", tags=["teams"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    name: str


class ProjectCreate(BaseModel):
    name: str


class TeamOut(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ProjectOut(BaseModel):
    id: UUID
    team_id: UUID
    name: str

    model_config = {"from_attributes": True}


class ApiKeyCreated(BaseModel):
    id: UUID
    team_id: UUID
    key: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyOut(BaseModel):
    id: UUID
    team_id: UUID
    status: str
    created_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


# ── Team endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(body: TeamCreate, session: AsyncSession = Depends(get_session)):
    team = Team(name=body.name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


@router.get("", response_model=list[TeamOut])
async def list_teams(
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Team).where(Team.id == current_key.team_id))
    return result.scalars().all()


# ── Project endpoints (nested under a team) ──────────────────────────────────


@router.post("/{team_id}/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    team_id: UUID,
    body: ProjectCreate,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")

    team = await session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    project = Project(team_id=team_id, name=body.name)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{team_id}/projects", response_model=list[ProjectOut])
async def list_projects(
    team_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")
    result = await session.execute(select(Project).where(Project.team_id == team_id))
    return result.scalars().all()


# ── API key endpoints ────────────────────────────────────────────────────────


@router.post("/{team_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(team_id: UUID, session: AsyncSession = Depends(get_session)):
    team = await session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    raw_key = "sk-" + secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = ApiKey(team_id=team_id, key_hash=key_hash)
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    return ApiKeyCreated(
        id=api_key.id,
        team_id=api_key.team_id,
        key=raw_key,
        created_at=api_key.created_at,
    )


@router.get("/{team_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    team_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")
    result = await session.execute(
        select(ApiKey).where(ApiKey.team_id == team_id)
    )
    return result.scalars().all()


@router.delete("/{team_id}/api-keys/{key_id}", response_model=ApiKeyOut)
async def revoke_api_key(
    team_id: UUID,
    key_id: UUID,
    current_key: ApiKey = Depends(get_api_key),
    session: AsyncSession = Depends(get_session),
):
    if current_key.team_id != team_id:
        raise HTTPException(403, "API key does not belong to this team")

    api_key = await session.get(ApiKey, key_id)
    if not api_key or api_key.team_id != team_id:
        raise HTTPException(404, "API key not found")
    if api_key.status == ApiKeyStatus.revoked:
        raise HTTPException(400, "API key already revoked")

    api_key.status = ApiKeyStatus.revoked
    api_key.revoked_at = datetime.utcnow()
    await session.commit()
    await session.refresh(api_key)
    return api_key
