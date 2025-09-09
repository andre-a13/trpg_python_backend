from http.client import HTTPException
from pydantic import Field
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel, HttpUrl, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import  Character
router = APIRouter()

SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Score = Annotated[int, Field(ge=0, le=100)]  # 0–100 (you can later warn if <20)

class SkillSet(BaseModel):
    corps: Score
    mental: Score
    social: Score

class CharacterCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    race: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
    slug : Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True , to_lower=True)]
    portraitUrl: HttpUrl | None = None
    stats: SkillSet
    skillsPrimary: list[SkillName] = []
    skillsSecondary: list[SkillName] = []
    inventory: list[SkillName] = []

@router.post("", status_code=201)
async def create_character(body: CharacterCreate, session: AsyncSession = Depends(get_session)):
    char = Character(
        slug=body.slug,
        name=body.name,
        race=body.race,
        portrait_url=str(body.portraitUrl) if body.portraitUrl else None,
        stats=body.stats.model_dump(),
        skills_primary=body.skillsPrimary,
        skills_secondary=body.skillsSecondary,
        inventory=body.inventory)    
    session.add(char)
    await session.commit()
    await session.refresh(char)
    return {"id": char.id, "name": char.name}

@router.get("", status_code=200)
async def list_characters(limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Character).order_by(Character.id).limit(limit).offset(offset)
    )
    rows = result.scalars().all()
    return [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "race": c.race,
            "portraitUrl": c.portrait_url,
            "stats": c.stats,
            "skillsPrimary": c.skills_primary,
            "skillsSecondary": c.skills_secondary,
            "inventory": c.inventory,
        }
        for c in rows
    ]
    
@router.get("/{slug}", status_code=200)
async def get_character_by_slug(slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Character).where(Character.slug == slug).limit(1)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")

    return {
        "id": c.id,
        "slug": c.slug,
        "name": c.name,
        "race": c.race,
        "portraitUrl": c.portrait_url,
        "stats": c.stats,
        "skillsPrimary": c.skills_primary,
        "skillsSecondary": c.skills_secondary,
        "inventory": c.inventory,
    }