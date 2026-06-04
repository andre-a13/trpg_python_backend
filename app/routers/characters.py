from annotated_types import Ge
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from typing import Annotated

from app.auth import require_current_user
from app.db import get_session
from app.models import Character, InventoryCategory, InventoryContent, User

router = APIRouter()

SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
InventoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
InventoryNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Score = Annotated[int, Field(ge=0, le=100)]


class SkillSet(BaseModel):
    corps: Score
    mental: Score
    social: Score


class CharacterCreate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
    race: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
    slug: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True, to_lower=True)]
    portraitUrl: HttpUrl | None = None
    backgroundUrl: HttpUrl | None = None
    stats: SkillSet
    skillsPrimary: list[SkillName] = []
    skillsSecondary: list[SkillName] = []
    inventory: list[SkillName] = []
    gold: Annotated[int, Ge(0)] = 0
    notes: str | None = None
    current_hp: Annotated[int, Ge(0)] = 0
    bonusHealth: Annotated[int, Ge(0)] = 0


class SkillSetPartial(BaseModel):
    corps: Score | None = None
    mental: Score | None = None
    social: Score | None = None


class CharacterUpdate(BaseModel):
    slug: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True, to_lower=True, pattern=r"^[a-z0-9-]+$")] | None = None
    name: Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)] | None = None
    race: Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)] | None = None
    portraitUrl: HttpUrl | None = None
    backgroundUrl: HttpUrl | None = None
    stats: SkillSetPartial | None = None
    skillsPrimary: list[SkillName] | None = None
    skillsSecondary: list[SkillName] | None = None
    inventory: list[SkillName] | None = None
    gold: Annotated[int, Ge(0)] | None = None
    notes: str | None = None
    current_hp: Annotated[int, Ge(0)] | None = None
    bonusHealth: Annotated[int, Ge(0)] | None = None


class InventoryCategoryCreate(BaseModel):
    name: InventoryName


class InventoryCategoryUpdate(BaseModel):
    name: InventoryName | None = None
    sortOrder: Annotated[int, Ge(0)] | None = None


class InventoryContentCreate(BaseModel):
    name: InventoryName
    quantity: Annotated[int, Ge(0)] = 1
    notes: InventoryNotes | None = None


class InventoryContentUpdate(BaseModel):
    name: InventoryName | None = None
    quantity: Annotated[int, Ge(0)] | None = None
    notes: InventoryNotes | None = None
    sortOrder: Annotated[int, Ge(0)] | None = None


class ReorderEntry(BaseModel):
    id: int
    sortOrder: Annotated[int, Ge(0)]


class ReorderRequest(BaseModel):
    items: list[ReorderEntry]


def serialize_inventory_content(item: InventoryContent):
    return {
        "id": item.id,
        "categoryId": item.category_id,
        "name": item.name,
        "quantity": item.quantity,
        "notes": item.notes,
        "sortOrder": item.sort_order,
    }


def serialize_inventory_category(category: InventoryCategory):
    return {
        "id": category.id,
        "characterId": category.character_id,
        "name": category.name,
        "sortOrder": category.sort_order,
        "contents": [
            serialize_inventory_content(item)
            for item in sorted(category.contents, key=lambda row: (row.sort_order, row.id))
        ],
    }


def serialize_character(c: Character, include_inventory_categories: bool = False):
    body = {
        "id": c.id,
        "slug": c.slug,
        "name": c.name,
        "race": c.race,
        "portraitUrl": c.portrait_url,
        "backgroundUrl": c.background_url,
        "stats": c.stats,
        "skillsPrimary": c.skills_primary,
        "skillsSecondary": c.skills_secondary,
        "inventory": c.inventory,
        "gold": c.gold,
        "notes": c.notes,
        "current_hp": c.current_hp,
        "bonusHealth": c.bonus_health,
        "teams": [
            {
                "uuid": team.uuid,
                "name": team.name,
                "illustrationUrl": team.illustration_url,
            }
            for team in c.teams
        ],
    }

    if include_inventory_categories:
        body["inventoryCategories"] = [
            serialize_inventory_category(category)
            for category in sorted(c.inventory_categories, key=lambda item: (item.sort_order, item.id))
        ]

    return body


async def get_character_or_404(
    slug: str,
    session: AsyncSession,
    include_inventory_categories: bool = False,
) -> Character:
    options = [selectinload(Character.teams)]
    if include_inventory_categories:
        options.append(selectinload(Character.inventory_categories).selectinload(InventoryCategory.contents))

    result = await session.execute(
        select(Character).options(*options).where(Character.slug == slug).limit(1)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


async def get_inventory_category_or_404(
    slug: str,
    category_id: int,
    session: AsyncSession,
) -> tuple[Character, InventoryCategory]:
    character = await get_character_or_404(slug, session)
    result = await session.execute(
        select(InventoryCategory)
        .options(selectinload(InventoryCategory.contents))
        .where(
            InventoryCategory.id == category_id,
            InventoryCategory.character_id == character.id,
        )
        .limit(1)
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Inventory category not found")
    return character, category


async def get_inventory_content_or_404(
    slug: str,
    category_id: int,
    item_id: int,
    session: AsyncSession,
) -> tuple[Character, InventoryCategory, InventoryContent]:
    character, category = await get_inventory_category_or_404(slug, category_id, session)
    result = await session.execute(
        select(InventoryContent)
        .where(
            InventoryContent.id == item_id,
            InventoryContent.category_id == category.id,
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return character, category, item


async def next_category_sort_order(character_id: int, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.max(InventoryCategory.sort_order)).where(InventoryCategory.character_id == character_id)
    )
    value = result.scalar_one_or_none()
    return 0 if value is None else value + 1


async def next_content_sort_order(category_id: int, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.max(InventoryContent.sort_order)).where(InventoryContent.category_id == category_id)
    )
    value = result.scalar_one_or_none()
    return 0 if value is None else value + 1


@router.post("", status_code=201)
async def create_character(
    body: CharacterCreate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.execute(select(Character.id).where(Character.slug == body.slug).limit(1))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Character slug already exists")

    char = Character(
        slug=body.slug,
        name=body.name,
        race=body.race,
        portrait_url=str(body.portraitUrl) if body.portraitUrl else None,
        background_url=str(body.backgroundUrl) if body.backgroundUrl else None,
        stats=body.stats.model_dump(),
        skills_primary=body.skillsPrimary,
        skills_secondary=body.skillsSecondary,
        inventory=body.inventory,
        gold=body.gold,
        notes=body.notes,
        current_hp=body.current_hp,
        bonus_health=body.bonusHealth,
    )
    session.add(char)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Character slug already exists")
    await session.refresh(char)
    return {"id": char.id, "name": char.name}


@router.get("", status_code=200)
async def list_characters(
    limit: int = 50,
    offset: int = 0,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Character)
        .options(selectinload(Character.teams))
        .order_by(Character.id)
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [serialize_character(c) for c in rows]


@router.post("/{slug}/inventory-categories", status_code=201)
async def create_inventory_category(
    slug: str,
    body: InventoryCategoryCreate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    category = InventoryCategory(
        character_id=character.id,
        name=body.name,
        sort_order=await next_category_sort_order(character.id, session),
    )
    session.add(category)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Inventory category already exists")
    await session.refresh(category, attribute_names=["contents"])
    return serialize_inventory_category(category)


@router.patch("/{slug}/inventory-categories/reorder", status_code=200)
async def reorder_inventory_categories(
    slug: str,
    body: ReorderRequest,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    ids = [item.id for item in body.items]
    result = await session.execute(
        select(InventoryCategory).where(
            InventoryCategory.character_id == character.id,
            InventoryCategory.id.in_(ids),
        )
    )
    categories = {category.id: category for category in result.scalars().all()}
    if len(categories) != len(set(ids)):
        raise HTTPException(status_code=404, detail="Inventory category not found")
    for item in body.items:
        categories[item.id].sort_order = item.sortOrder
    await session.commit()
    refreshed = await get_character_or_404(slug, session, include_inventory_categories=True)
    return [serialize_inventory_category(category) for category in refreshed.inventory_categories]


@router.patch("/{slug}/inventory-categories/{category_id}", status_code=200)
async def patch_inventory_category(
    slug: str,
    category_id: int,
    body: InventoryCategoryUpdate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, category = await get_inventory_category_or_404(slug, category_id, session)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        category.name = data["name"]
    if "sortOrder" in data:
        category.sort_order = data["sortOrder"]
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Inventory category already exists")
    await session.refresh(category, attribute_names=["contents"])
    return serialize_inventory_category(category)


@router.delete("/{slug}/inventory-categories/{category_id}", status_code=204)
async def delete_inventory_category(
    slug: str,
    category_id: int,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, category = await get_inventory_category_or_404(slug, category_id, session)
    await session.delete(category)
    await session.commit()
    return None


@router.post("/{slug}/inventory-categories/{category_id}/items", status_code=201)
async def create_inventory_content(
    slug: str,
    category_id: int,
    body: InventoryContentCreate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, category = await get_inventory_category_or_404(slug, category_id, session)
    item = InventoryContent(
        category_id=category.id,
        name=body.name,
        quantity=body.quantity,
        notes=body.notes,
        sort_order=await next_content_sort_order(category.id, session),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return serialize_inventory_content(item)


@router.patch("/{slug}/inventory-categories/{category_id}/items/reorder", status_code=200)
async def reorder_inventory_content(
    slug: str,
    category_id: int,
    body: ReorderRequest,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, category = await get_inventory_category_or_404(slug, category_id, session)
    ids = [item.id for item in body.items]
    result = await session.execute(
        select(InventoryContent).where(
            InventoryContent.category_id == category.id,
            InventoryContent.id.in_(ids),
        )
    )
    contents = {item.id: item for item in result.scalars().all()}
    if len(contents) != len(set(ids)):
        raise HTTPException(status_code=404, detail="Inventory item not found")
    for item in body.items:
        contents[item.id].sort_order = item.sortOrder
    await session.commit()
    await session.refresh(category, attribute_names=["contents"])
    return [serialize_inventory_content(item) for item in category.contents]


@router.patch("/{slug}/inventory-categories/{category_id}/items/{item_id}", status_code=200)
async def patch_inventory_content(
    slug: str,
    category_id: int,
    item_id: int,
    body: InventoryContentUpdate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, _, item = await get_inventory_content_or_404(slug, category_id, item_id, session)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        item.name = data["name"]
    if "quantity" in data:
        item.quantity = data["quantity"]
    if "notes" in data:
        item.notes = data["notes"]
    if "sortOrder" in data:
        item.sort_order = data["sortOrder"]
    await session.commit()
    await session.refresh(item)
    return serialize_inventory_content(item)


@router.delete("/{slug}/inventory-categories/{category_id}/items/{item_id}", status_code=204)
async def delete_inventory_content(
    slug: str,
    category_id: int,
    item_id: int,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, _, item = await get_inventory_content_or_404(slug, category_id, item_id, session)
    await session.delete(item)
    await session.commit()
    return None


@router.get("/{slug}", status_code=200)
async def get_character_by_slug(
    slug: str,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = await get_character_or_404(slug, session, include_inventory_categories=True)
    return serialize_character(c, include_inventory_categories=True)


@router.patch("/{slug}", status_code=200)
async def patch_character(
    slug: str,
    body: CharacterUpdate,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    c = await get_character_or_404(slug, session)
    data = body.model_dump(exclude_unset=True)

    if "slug" in data:
        existing = await session.execute(
            select(Character.id).where(Character.slug == data["slug"], Character.id != c.id).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Character slug already exists")
        c.slug = data["slug"]
    if "name" in data:
        c.name = data["name"]
    if "race" in data:
        c.race = data["race"]
    if "portraitUrl" in data:
        c.portrait_url = str(data["portraitUrl"]) if data["portraitUrl"] else None
    if "backgroundUrl" in data:
        c.background_url = str(data["backgroundUrl"]) if data["backgroundUrl"] else None
    if "stats" in data:
        c.stats = {**(c.stats or {}), **{k: v for k, v in data["stats"].items() if v is not None}}
        flag_modified(c, "stats")
    if "skillsPrimary" in data:
        c.skills_primary = data["skillsPrimary"]
    if "skillsSecondary" in data:
        c.skills_secondary = data["skillsSecondary"]
    if "inventory" in data:
        c.inventory = data["inventory"]
    if "gold" in data:
        c.gold = data["gold"]
    if "notes" in data:
        c.notes = data["notes"]
    if "current_hp" in data:
        c.current_hp = data["current_hp"]
    if "bonusHealth" in data:
        c.bonus_health = data["bonusHealth"]

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Character slug already exists")
    await session.refresh(c)
    return serialize_character(c)
