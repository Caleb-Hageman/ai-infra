from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Project, Team

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


# ── Team endpoints ───────────────────────────────────────────────────────────


@router.post("", response_model=TeamOut, status_code=201)
async def create_team(body: TeamCreate, session: AsyncSession = Depends(get_session)):
    team = Team(name=body.name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


@router.get("", response_model=list[TeamOut])
async def list_teams(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Team))
    return result.scalars().all()


# ── Project endpoints (nested under a team) ──────────────────────────────────


@router.post("/{team_id}/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    team_id: UUID, body: ProjectCreate, session: AsyncSession = Depends(get_session)
):
    team = await session.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    project = Project(team_id=team_id, name=body.name)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{team_id}/projects", response_model=list[ProjectOut])
async def list_projects(team_id: UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).where(Project.team_id == team_id))
    return result.scalars().all()
