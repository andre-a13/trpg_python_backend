import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import is_admin, require_admin_user, require_current_user
from app.db import get_session
from app.models import Character, CharacterInvention, Invention, User
from app.routers.characters import get_character_or_404, require_character_visible, require_character_write
from app.schemas.errors import ApiError
from app.schemas.inventions import (
    InventionCreate,
    InventionResponse,
    InventionStateResponse,
    InvengineerStatusResponse,
    InvengineerUpdate,
)


router = APIRouter()
DRAW_COUNT = 5


def serialize_invention(item: Invention) -> dict:
    return {"id": item.id, "name": item.name, "description": item.description}


async def invention_state(character: Character, current_user: User, session: AsyncSession) -> dict:
    result = await session.execute(
        select(CharacterInvention)
        .options(selectinload(CharacterInvention.invention))
        .where(CharacterInvention.character_id == character.id)
        .order_by(CharacterInvention.position)
    )
    return {
        "enabled": character.invengineer_enabled,
        "drawCount": DRAW_COUNT,
        "permissions": {"canDraw": is_admin(current_user) or character.owner_user_id == current_user.id},
        "items": [serialize_invention(row.invention) for row in result.scalars()],
    }


@router.get("/inventions", operation_id="inventionsList", response_model=list[InventionResponse],
            responses={401: {"model": ApiError}, 403: {"model": ApiError}})
async def list_inventions(
    current_user: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Invention).where(Invention.is_active.is_(True)).order_by(Invention.id))
    return [serialize_invention(item) for item in result.scalars()]


@router.post("/inventions", status_code=status.HTTP_201_CREATED, operation_id="inventionsCreate",
             response_model=InventionResponse,
             responses={401: {"model": ApiError}, 403: {"model": ApiError}, 409: {"model": ApiError}})
async def add_invention(
    body: InventionCreate,
    current_user: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    name = unicodedata.normalize("NFC", body.name)
    key = name.casefold()
    item = await session.scalar(select(Invention).where(Invention.name_key == key))
    if item is not None and item.is_active:
        raise HTTPException(status_code=409, detail="Invention already exists")
    if item is None:
        item = Invention(name=name, name_key=key, description="")
        session.add(item)
    else:
        item.is_active = True
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Invention already exists")
    return serialize_invention(item)


@router.delete("/inventions/{invention_id}", status_code=status.HTTP_204_NO_CONTENT,
               operation_id="inventionsDelete",
               responses={401: {"model": ApiError}, 403: {"model": ApiError}, 404: {"model": ApiError}})
async def remove_invention(
    invention_id: int,
    current_user: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(Invention, invention_id)
    if item is None or not item.is_active:
        raise HTTPException(status_code=404, detail="Invention not found")
    # Retain references from existing draws while excluding future draws.
    item.is_active = False
    await session.commit()


@router.patch("/characters/{slug}/invengineer", operation_id="invengineerSetEnabled",
              response_model=InvengineerStatusResponse,
              responses={401: {"model": ApiError}, 403: {"model": ApiError}, 404: {"model": ApiError}})
async def set_invengineer_enabled(
    slug: str,
    body: InvengineerUpdate,
    current_user: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    character.invengineer_enabled = body.enabled
    await session.commit()
    return {"enabled": character.invengineer_enabled}


@router.get("/characters/{slug}/inventions", operation_id="inventionsGetState",
            response_model=InventionStateResponse,
            responses={401: {"model": ApiError}, 404: {"model": ApiError}})
async def get_character_inventions(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    await require_character_visible(character, current_user, session)
    return await invention_state(character, current_user, session)


@router.post("/characters/{slug}/inventions/draw", operation_id="inventionsDraw",
             response_model=InventionStateResponse,
             responses={401: {"model": ApiError}, 403: {"model": ApiError},
                        404: {"model": ApiError}, 409: {"model": ApiError}})
async def draw_inventions(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    await require_character_visible(character, current_user, session)
    require_character_write(character, current_user)
    # Acquire the SQLite write lock before reading the catalogue and replacing
    # associations, so simultaneous requests cannot mix two sets of inventions.
    claimed = await session.execute(
        update(Character)
        .where(Character.id == character.id, Character.invengineer_enabled.is_(True))
        .values(invengineer_enabled=True)
    )
    if claimed.rowcount != 1:
        raise HTTPException(status_code=403, detail="Invengineer module is inactive")
    result = await session.execute(
        select(Invention).where(Invention.is_active.is_(True)).order_by(func.random()).limit(DRAW_COUNT)
    )
    items = list(result.scalars())
    if len(items) < DRAW_COUNT:
        raise HTTPException(status_code=409, detail=f"At least {DRAW_COUNT} active inventions are required")
    await session.execute(delete(CharacterInvention).where(CharacterInvention.character_id == character.id))
    session.add_all([
        CharacterInvention(character_id=character.id, invention_id=item.id, position=position)
        for position, item in enumerate(items)
    ])
    # Cooldown is intentionally client-only, stored in localStorage.
    state = {
        "enabled": True,
        "drawCount": DRAW_COUNT,
        "permissions": {"canDraw": True},
        "items": [serialize_invention(item) for item in items],
    }
    await session.commit()
    return state
