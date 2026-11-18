import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin, require_admin_user, require_current_user
from app.db import get_session
from app.models import Character, CharacterLightWord, LightBook, LightWord, User
from app.routers.characters import get_character_or_404, require_character_visible
from app.schemas.errors import ApiError
from app.schemas.light import (
    LightBookResponse,
    LightBookSettingsResponse,
    LightBookSettingsUpdate,
    LightWordCreate,
    LightWordResponse,
)


router = APIRouter()
admin_errors = {401: {"model": ApiError}, 403: {"model": ApiError}}
character_read_errors = {401: {"model": ApiError}, 404: {"model": ApiError}}
character_write_errors = {**character_read_errors, 403: {"model": ApiError}}


def word_response(word: LightWord) -> LightWordResponse:
    return LightWordResponse(id=word.id, name=word.name, description=word.description)


async def known_words(character_id: int, session: AsyncSession) -> list[LightWord]:
    result = await session.scalars(
        select(LightWord)
        .join(CharacterLightWord, CharacterLightWord.word_id == LightWord.id)
        .where(CharacterLightWord.character_id == character_id)
        .order_by(LightWord.name_key)
    )
    return list(result)


@router.get("/light/words", operation_id="lightWordsList", response_model=list[LightWordResponse | None],
            responses={401: {"model": ApiError}})
async def list_light_words(
    response: Response,
    user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    response.headers["Cache-Control"] = "private, no-store"
    words = await session.scalars(select(LightWord).order_by(LightWord.id))
    if is_admin(user):
        return [word_response(word) for word in words]

    known_ids = set(await session.scalars(
        select(CharacterLightWord.word_id)
        .join(Character, Character.id == CharacterLightWord.character_id)
        .where(Character.owner_user_id == user.id)
    ))
    return [word_response(word) if word.id in known_ids else None for word in words]


@router.post("/light/words", status_code=status.HTTP_201_CREATED, operation_id="lightWordsCreate",
             response_model=LightWordResponse, responses={**admin_errors, 409: {"model": ApiError}})
async def create_light_word(
    body: LightWordCreate,
    _admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    name = unicodedata.normalize("NFC", body.name)
    word = LightWord(name=name, name_key=name.casefold(), description=body.description)
    session.add(word)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Light word already exists")
    return word_response(word)


@router.get("/light/books/settings", operation_id="lightBooksListSettings",
            response_model=dict[str, LightBookSettingsResponse], responses=admin_errors)
async def list_light_book_settings(
    _admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.execute(select(LightBook.character_id, LightBook.slot_count))
    return {str(character_id): LightBookSettingsResponse(slotCount=slots) for character_id, slots in rows}


@router.put("/characters/{slug}/light-book/settings", operation_id="lightBooksSetSettings",
            response_model=LightBookSettingsResponse, responses=character_write_errors)
async def set_light_book_settings(
    slug: str,
    body: LightBookSettingsUpdate,
    _admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session, include_sheet_details=False)
    await session.execute(
        insert(LightBook)
        .values(character_id=character.id, slot_count=body.slotCount)
        .on_conflict_do_update(index_elements=[LightBook.character_id], set_={"slot_count": body.slotCount})
    )
    await session.commit()
    return LightBookSettingsResponse(slotCount=body.slotCount)


@router.get("/characters/{slug}/light-book", operation_id="lightBooksGet",
            response_model=LightBookResponse, responses=character_read_errors)
async def get_light_book(
    slug: str,
    response: Response,
    user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session, include_sheet_details=False)
    await require_character_visible(character, user, session)
    response.headers["Cache-Control"] = "private, no-store"
    if not (is_admin(user) or character.owner_user_id == user.id):
        return LightBookResponse(slotCount=None, words=[])
    book = await session.get(LightBook, character.id)
    words = await known_words(character.id, session)
    return LightBookResponse(slotCount=book.slot_count if book else 0, words=[word_response(word) for word in words])


@router.put("/characters/{slug}/light-book/words/{word_id}", status_code=status.HTTP_204_NO_CONTENT,
            operation_id="lightBooksUnlockWord", responses=character_write_errors)
async def unlock_light_word(
    slug: str,
    word_id: Annotated[int, Path(gt=0, le=9007199254740991)],
    _admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session, include_sheet_details=False)
    if await session.get(LightWord, word_id) is None:
        raise HTTPException(status_code=404, detail="Light word not found")
    await session.execute(
        insert(CharacterLightWord)
        .values(character_id=character.id, word_id=word_id)
        .on_conflict_do_nothing(index_elements=[CharacterLightWord.character_id, CharacterLightWord.word_id])
    )
    await session.commit()
