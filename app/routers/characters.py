from http.client import HTTPException
from annotated_types import Ge
from pydantic import Field
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel, HttpUrl, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.models import  Character
from sqlalchemy.orm.attributes import flag_modified

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
    gold: Annotated[int, Ge(0)] = 0  # new field with default value
    notes : str | None = None  # new field with default value
    
class SkillSetPartial(BaseModel):
    corps: Score | None = None
    mental: Score | None = None
    social: Score | None = None

class CharacterUpdate(BaseModel):
    slug: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True, to_lower=True, pattern=r'^[a-z0-9-]+$')] | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)] | None = None
    race: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)] | None = None
    portraitUrl: HttpUrl | None = None
    stats: SkillSetPartial | None = None
    skillsPrimary: list[SkillName] | None = None
    skillsSecondary: list[SkillName] | None = None
    inventory: list[SkillName] | None = None
    gold: Annotated[int, Ge(0)] | None = None 
    notes : str | None = None

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
            "gold": c.gold,
            "notes": c.notes,
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
        "gold": c.gold,
        "notes": c.notes,
    }

@router.patch("/{slug}", status_code=200)
async def patch_character(slug: str, body: CharacterUpdate, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Character).where(Character.slug == slug).limit(1))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")

    data = body.model_dump(exclude_unset=True)
    if "slug" in data: c.slug = data["slug"]
    if "name" in data: c.name = data["name"]
    if "race" in data: c.race = data["race"]
    if "portraitUrl" in data: c.portrait_url = str(data["portraitUrl"]) if data["portraitUrl"] else None
    if "stats" in data:
        c.stats = {**(c.stats or {}), **{k: v for k, v in data["stats"].items() if v is not None}}
        flag_modified(c, "stats")  # tell SQLAlchemy the JSON changed
    if "skillsPrimary" in data: c.skills_primary = data["skillsPrimary"]
    if "skillsSecondary" in data: c.skills_secondary = data["skillsSecondary"]
    if "inventory" in data: c.inventory = data["inventory"]
    if "gold" in data: c.gold = data["gold"]  
    if "notes" in data: c.notes = data["notes"]
    
    
    await session.commit()
    await session.refresh(c)
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
        "gold": c.gold,
        "notes": c.notes,
    }