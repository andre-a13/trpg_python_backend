from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import is_admin, require_admin_user, require_current_user
from app.db import get_session
from app.models import Character, Team, User, character_teams

router = APIRouter()


TeamName = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]


class TeamCreate(BaseModel):
    uuid: UUID | None = None
    name: TeamName
    illustrationUrl: HttpUrl | None = None


class TeamUpdate(BaseModel):
    name: TeamName | None = None
    illustrationUrl: HttpUrl | None = None


def serialize_team(team: Team):
    return {
        "uuid": team.uuid,
        "name": team.name,
        "illustrationUrl": team.illustration_url,
        "characters": [
            {
                "id": character.id,
                "slug": character.slug,
                "name": character.name,
                "race": character.race,
                "portraitUrl": character.portrait_url,
                "ownerUserId": character.owner_user_id,
            }
            for character in team.characters
        ],
    }


async def get_team_or_404(team_uuid: UUID, session: AsyncSession) -> Team:
    result = await session.execute(
        select(Team)
        .options(selectinload(Team.characters))
        .where(Team.uuid == str(team_uuid))
        .limit(1)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def get_character_or_404(slug: str, session: AsyncSession) -> Character:
    result = await session.execute(
        select(Character).where(Character.slug == slug).limit(1)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


def owned_team_uuids_query(user_id: int):
    return (
        select(character_teams.c.team_uuid)
        .join(Character, Character.id == character_teams.c.character_id)
        .where(Character.owner_user_id == user_id)
    )


async def require_team_visible(team: Team, current_user: User, session: AsyncSession) -> None:
    if is_admin(current_user):
        return

    result = await session.execute(
        select(character_teams.c.team_uuid)
        .join(Character, Character.id == character_teams.c.character_id)
        .where(
            character_teams.c.team_uuid == team.uuid,
            Character.owner_user_id == current_user.id,
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Team not found")


@router.post("", status_code=201)
async def create_team(
    body: TeamCreate,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    team_data = {
        "name": body.name,
        "illustration_url": str(body.illustrationUrl) if body.illustrationUrl else None,
        "characters": [],
    }
    if body.uuid:
        team_data["uuid"] = str(body.uuid)
    team = Team(**team_data)
    session.add(team)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Team UUID already exists")
    return serialize_team(team)


@router.get("", status_code=200)
async def list_teams(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(Team)
        .options(selectinload(Team.characters))
        .order_by(Team.name, Team.uuid)
        .limit(limit)
        .offset(offset)
    )
    if not is_admin(current_user):
        query = query.where(Team.uuid.in_(owned_team_uuids_query(current_user.id)))

    result = await session.execute(
        query
    )
    rows = result.scalars().all()
    return [serialize_team(team) for team in rows]


@router.get("/{team_uuid}", status_code=200)
async def get_team(
    team_uuid: UUID,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_team_or_404(team_uuid, session)
    await require_team_visible(team, current_user, session)
    return serialize_team(team)


@router.patch("/{team_uuid}", status_code=200)
async def patch_team(
    team_uuid: UUID,
    body: TeamUpdate,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_team_or_404(team_uuid, session)
    data = body.model_dump(exclude_unset=True)

    if "name" in data:
        team.name = data["name"]
    if "illustrationUrl" in data:
        team.illustration_url = str(data["illustrationUrl"]) if data["illustrationUrl"] else None

    await session.commit()
    return serialize_team(team)


@router.post("/{team_uuid}/characters/{character_slug}", status_code=200)
async def add_character_to_team(
    team_uuid: UUID,
    character_slug: str,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_team_or_404(team_uuid, session)
    character = await get_character_or_404(character_slug, session)
    if character not in team.characters:
        team.characters.append(character)
        await session.commit()
    return serialize_team(team)


@router.delete("/{team_uuid}/characters/{character_slug}", status_code=200)
async def remove_character_from_team(
    team_uuid: UUID,
    character_slug: str,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    team = await get_team_or_404(team_uuid, session)
    character = await get_character_or_404(character_slug, session)
    if character in team.characters:
        team.characters.remove(character)
        await session.commit()
    return serialize_team(team)
