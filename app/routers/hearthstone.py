import hashlib
import json
import secrets
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl, StringConstraints
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import is_admin, require_admin_user, require_current_user
from app.db import get_session
from app.hearthstone_catalog import (
    collectible_card_sets,
    find_collectible_card,
    illustration_url,
    random_collectible_cards,
    render_url,
    search_collectible_cards,
)
from app.models import Character, CharacterDeck, DeckCardCopy, DeckCardDefinition, User
from app.routers.characters import get_character_or_404, require_character_visible


router = APIRouter()
CardName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CardText = Annotated[str, StringConstraints(max_length=10000)]
CardMetadata = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
NonNegative = Annotated[int, Field(ge=0)]


class HearthstomancerUpdate(BaseModel):
    enabled: bool


class DeckDefinitionInput(BaseModel):
    sourceCardId: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    name: CardName | None = None
    cost: NonNegative | None = None
    attack: NonNegative | None = None
    health: NonNegative | None = None
    durability: NonNegative | None = None
    text: CardText | None = None
    cardType: CardMetadata | None = None
    rarity: CardMetadata | None = None
    cardClass: CardMetadata | None = None
    tribe: CardMetadata | None = None
    spellSchool: CardMetadata | None = None
    cardSet: CardMetadata | None = None
    illustrationUrl: HttpUrl | None = None
    normalCount: NonNegative = 0
    goldenCount: NonNegative = 0


class DeckCompositionUpdate(BaseModel):
    definitions: list[DeckDefinitionInput] = Field(default_factory=list)


class DeckRemoveRequest(BaseModel):
    zone: Literal["deck"]
    definitionId: int
    isGolden: bool


class DeckPackOpenRequest(BaseModel):
    cardSet: CardMetadata


class DeckPackSaveRequest(BaseModel):
    sourceCardIds: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    ] = Field(min_length=5, max_length=5)


def can_manage_deck(character: Character, current_user: User) -> bool:
    return is_admin(current_user) or character.owner_user_id == current_user.id


def require_deck_manager(character: Character, current_user: User) -> None:
    if not can_manage_deck(character, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Deck write access required")


def require_active_deck(deck: CharacterDeck) -> None:
    if not deck.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hearthstomancer deck is inactive")


async def load_deck(character_id: int, session: AsyncSession) -> CharacterDeck | None:
    result = await session.execute(
        select(CharacterDeck)
        .options(selectinload(CharacterDeck.definitions).selectinload(DeckCardDefinition.copies))
        .where(CharacterDeck.character_id == character_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def require_deck(character_id: int, session: AsyncSession) -> CharacterDeck:
    deck = await load_deck(character_id, session)
    if deck is None:
        raise HTTPException(status_code=404, detail="Hearthstomancer deck not configured")
    return deck


async def deck_context(
    slug: str,
    current_user: User,
    session: AsyncSession,
) -> tuple[Character, CharacterDeck]:
    character = await get_character_or_404(slug, session)
    await require_character_visible(character, current_user, session)
    deck = await require_deck(character.id, session)
    return character, deck


def next_shuffle_key() -> int:
    return secrets.randbits(63)


async def claim_revision(deck: CharacterDeck, session: AsyncSession) -> None:
    expected_revision = deck.revision
    result = await session.execute(
        update(CharacterDeck)
        .where(CharacterDeck.id == deck.id, CharacterDeck.revision == expected_revision)
        .values(revision=expected_revision + 1, updated_at=datetime.utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deck changed concurrently; reload and retry")
    deck.revision = expected_revision + 1


async def delete_copy_and_orphan_definition(copy: DeckCardCopy, session: AsyncSession) -> None:
    count_result = await session.execute(
        select(func.count(DeckCardCopy.id)).where(
            DeckCardCopy.definition_id == copy.definition_id,
            DeckCardCopy.id != copy.id,
        )
    )
    if count_result.scalar_one() == 0:
        definition = await session.get(DeckCardDefinition, copy.definition_id)
        if definition is not None:
            await session.delete(definition)
    else:
        await session.delete(copy)
    await session.flush()


async def finalize_undo(deck: CharacterDeck, session: AsyncSession) -> None:
    if deck.undo_copy_id is None:
        return
    copy = await session.get(DeckCardCopy, deck.undo_copy_id)
    deck.undo_copy_id = None
    if copy is None or copy.zone != "destroyed":
        return
    await delete_copy_and_orphan_definition(copy, session)


async def reshuffle_remaining(deck_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(DeckCardCopy)
        .join(DeckCardDefinition, DeckCardDefinition.id == DeckCardCopy.definition_id)
        .where(DeckCardDefinition.deck_id == deck_id, DeckCardCopy.zone == "deck")
    )
    for copy in result.scalars():
        copy.shuffle_key = next_shuffle_key()


def definition_values(payload: DeckDefinitionInput) -> dict:
    source = find_collectible_card(payload.sourceCardId)
    if source is None:
        raise HTTPException(status_code=422, detail=f"Unknown collectible card: {payload.sourceCardId}")

    values = {
        "source_card_id": payload.sourceCardId,
        "name": payload.name or source["name"],
        "cost": payload.cost if payload.cost is not None else source.get("cost"),
        "attack": payload.attack if payload.attack is not None else source.get("attack"),
        "health": payload.health if payload.health is not None else source.get("health"),
        "durability": payload.durability if payload.durability is not None else source.get("durability"),
        "effect_text": payload.text if payload.text is not None else source.get("text", ""),
        "card_type": payload.cardType if payload.cardType is not None else source.get("cardType"),
        "rarity": payload.rarity if payload.rarity is not None else source.get("rarity"),
        "card_class": payload.cardClass if payload.cardClass is not None else source.get("cardClass"),
        "tribe": payload.tribe if payload.tribe is not None else source.get("tribe"),
        "spell_school": payload.spellSchool if payload.spellSchool is not None else source.get("spellSchool"),
        "card_set": payload.cardSet if payload.cardSet is not None else source.get("cardSet"),
        "illustration_url": str(payload.illustrationUrl) if payload.illustrationUrl else source["illustrationUrl"],
    }
    values["name"] = values["name"].strip()
    values["effect_text"] = values["effect_text"].replace("\r\n", "\n").strip()
    if not values["name"]:
        raise HTTPException(status_code=422, detail="Card name cannot be empty")
    for key in ("card_type", "rarity", "card_class", "tribe", "spell_school", "card_set"):
        if isinstance(values[key], str):
            values[key] = values[key].strip() or None
    return values


def definition_fingerprint(values: dict) -> str:
    editable_values = {
        key: values[key]
        for key in (
            "name",
            "cost",
            "attack",
            "health",
            "durability",
            "effect_text",
            "card_type",
            "rarity",
            "card_class",
            "tribe",
            "spell_school",
            "card_set",
            "illustration_url",
        )
    }
    encoded = json.dumps(editable_values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def definition_is_variant(definition: DeckCardDefinition) -> bool:
    try:
        original_values = definition_values(DeckDefinitionInput(sourceCardId=definition.source_card_id))
    except HTTPException:
        return True
    return definition.fingerprint != definition_fingerprint(original_values)


def serialize_definition(definition: DeckCardDefinition) -> dict:
    active_copies = [copy for copy in definition.copies if copy.zone in {"deck", "drawn"}]
    source_id = definition.source_card_id
    original_illustration = illustration_url(source_id) if source_id else None
    return {
        "id": definition.id,
        "sourceCardId": source_id,
        "name": definition.name,
        "cost": definition.cost,
        "attack": definition.attack,
        "health": definition.health,
        "durability": definition.durability,
        "text": definition.effect_text,
        "cardType": definition.card_type,
        "rarity": definition.rarity,
        "cardClass": definition.card_class,
        "tribe": definition.tribe,
        "spellSchool": definition.spell_school,
        "cardSet": definition.card_set,
        "illustrationUrl": definition.illustration_url,
        "originalIllustrationUrl": original_illustration,
        "renderUrl": render_url(source_id) if source_id else None,
        "isVariant": definition_is_variant(definition),
        "normalCount": sum(not copy.is_golden for copy in active_copies),
        "goldenCount": sum(copy.is_golden for copy in active_copies),
        "remainingNormalCount": sum(not copy.is_golden and copy.zone == "deck" for copy in active_copies),
        "remainingGoldenCount": sum(copy.is_golden and copy.zone == "deck" for copy in active_copies),
    }


def serialize_copy(copy: DeckCardCopy) -> dict:
    return {
        "copyId": copy.id,
        "isGolden": copy.is_golden,
        "definition": serialize_definition(copy.definition),
    }


def serialize_deck(character: Character, deck: CharacterDeck, current_user: User) -> dict:
    definitions = sorted(deck.definitions, key=lambda row: (row.name.casefold(), row.id))
    copies = [copy for definition in definitions for copy in definition.copies]
    active_copies = [copy for copy in copies if copy.zone in {"deck", "drawn"}]
    drawn = sorted((copy for copy in active_copies if copy.zone == "drawn"), key=lambda row: row.id)
    undo_copy = next((copy for copy in copies if copy.id == deck.undo_copy_id and copy.zone == "destroyed"), None)
    return {
        "configured": True,
        "enabled": deck.enabled,
        "revision": deck.revision,
        "permissions": {
            "canManage": can_manage_deck(character, current_user),
            "canActivate": is_admin(current_user),
        },
        "counts": {
            "total": len(active_copies),
            "remaining": sum(copy.zone == "deck" for copy in active_copies),
            "drawn": len(drawn),
        },
        "definitions": [serialize_definition(definition) for definition in definitions if any(
            copy.zone in {"deck", "drawn"} for copy in definition.copies
        )],
        "drawnCards": [serialize_copy(copy) for copy in drawn],
        "undoablePlay": serialize_copy(undo_copy) if undo_copy else None,
    }


async def commit_and_serialize(
    character: Character,
    deck: CharacterDeck,
    current_user: User,
    session: AsyncSession,
) -> dict:
    await session.commit()
    refreshed = await require_deck(character.id, session)
    return serialize_deck(character, refreshed, current_user)


@router.get("/hearthstone/cards")
async def list_hearthstone_cards(
    q: str = "",
    cardSet: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 50,
    _current_user: User = Depends(require_current_user),
):
    items, total = search_collectible_cards(q, page, pageSize, cardSet)
    return {
        "items": items,
        "sets": collectible_card_sets(),
        "page": page,
        "pageSize": pageSize,
        "total": total,
    }


@router.patch("/characters/{slug}/hearthstomancer")
async def set_hearthstomancer_status(
    slug: str,
    body: HearthstomancerUpdate,
    current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    character = await get_character_or_404(slug, session)
    deck = await load_deck(character.id, session)
    if deck is None:
        if not body.enabled:
            return {"configured": False, "enabled": False}
        deck = CharacterDeck(character_id=character.id, enabled=True)
        session.add(deck)
    else:
        deck.enabled = body.enabled
        deck.revision += 1
    await session.commit()
    refreshed = await require_deck(character.id, session)
    return serialize_deck(character, refreshed, current_admin)


@router.get("/characters/{slug}/deck")
async def get_character_deck(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    return serialize_deck(character, deck, current_user)


@router.post("/characters/{slug}/deck/pack/open")
async def open_card_pack(
    slug: str,
    body: DeckPackOpenRequest,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    cards = random_collectible_cards(body.cardSet, 5)
    if len(cards) != 5:
        raise HTTPException(status_code=422, detail="This set cannot provide a five-card pack")
    return {"cardSet": body.cardSet, "cards": cards}


@router.post("/characters/{slug}/deck/pack/save")
async def save_pack_to_deck(
    slug: str,
    body: DeckPackSaveRequest,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)

    if len(set(body.sourceCardIds)) != len(body.sourceCardIds):
        raise HTTPException(status_code=422, detail="Pack cards must be distinct")

    grouped: dict[str, dict] = {}
    for source_card_id in body.sourceCardIds:
        values = definition_values(DeckDefinitionInput(sourceCardId=source_card_id))
        fingerprint = definition_fingerprint(values)
        group = grouped.setdefault(fingerprint, {"values": values, "count": 0})
        group["count"] += 1

    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    for fingerprint, group in grouped.items():
        result = await session.execute(
            select(DeckCardDefinition).where(
                DeckCardDefinition.deck_id == deck.id,
                DeckCardDefinition.fingerprint == fingerprint,
            )
        )
        definition = result.scalar_one_or_none()
        if definition is None:
            definition = DeckCardDefinition(
                deck_id=deck.id,
                fingerprint=fingerprint,
                **group["values"],
            )
            session.add(definition)
            await session.flush()

        session.add_all([
            DeckCardCopy(
                definition_id=definition.id,
                is_golden=False,
                zone="deck",
                shuffle_key=next_shuffle_key(),
            )
            for _ in range(group["count"])
        ])
    return await commit_and_serialize(character, deck, current_user, session)


@router.put("/characters/{slug}/deck/composition")
async def replace_deck_composition(
    slug: str,
    body: DeckCompositionUpdate,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    await claim_revision(deck, session)
    await finalize_undo(deck, session)

    grouped: dict[str, dict] = {}
    for payload in body.definitions:
        if payload.normalCount + payload.goldenCount == 0:
            continue
        values = definition_values(payload)
        fingerprint = definition_fingerprint(values)
        group = grouped.setdefault(fingerprint, {
            "values": values,
            "normal_count": 0,
            "golden_count": 0,
        })
        group["normal_count"] += payload.normalCount
        group["golden_count"] += payload.goldenCount

    definition_ids = select(DeckCardDefinition.id).where(DeckCardDefinition.deck_id == deck.id)
    await session.execute(delete(DeckCardCopy).where(DeckCardCopy.definition_id.in_(definition_ids)))
    await session.execute(delete(DeckCardDefinition).where(DeckCardDefinition.deck_id == deck.id))
    await session.flush()

    for fingerprint, group in grouped.items():
        definition = DeckCardDefinition(deck_id=deck.id, fingerprint=fingerprint, **group["values"])
        session.add(definition)
        await session.flush()
        for is_golden, count in ((False, group["normal_count"]), (True, group["golden_count"])):
            session.add_all([
                DeckCardCopy(
                    definition_id=definition.id,
                    is_golden=is_golden,
                    zone="deck",
                    shuffle_key=next_shuffle_key(),
                )
                for _ in range(count)
            ])

    return await commit_and_serialize(character, deck, current_user, session)


@router.post("/characters/{slug}/deck/draw")
async def draw_card(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    result = await session.execute(
        select(DeckCardCopy)
        .join(DeckCardDefinition, DeckCardDefinition.id == DeckCardCopy.definition_id)
        .where(DeckCardDefinition.deck_id == deck.id, DeckCardCopy.zone == "deck")
        .order_by(DeckCardCopy.shuffle_key, DeckCardCopy.id)
        .limit(1)
    )
    copy = result.scalar_one_or_none()
    if copy is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deck is empty")
    copy.zone = "drawn"
    copy.shuffle_key = None
    return await commit_and_serialize(character, deck, current_user, session)


async def get_drawn_copy(copy_id: int, deck_id: int, session: AsyncSession) -> DeckCardCopy:
    result = await session.execute(
        select(DeckCardCopy)
        .join(DeckCardDefinition, DeckCardDefinition.id == DeckCardCopy.definition_id)
        .where(
            DeckCardCopy.id == copy_id,
            DeckCardCopy.zone == "drawn",
            DeckCardDefinition.deck_id == deck_id,
        )
    )
    copy = result.scalar_one_or_none()
    if copy is None:
        raise HTTPException(status_code=404, detail="Drawn card not found")
    return copy


@router.post("/characters/{slug}/deck/copies/{copy_id}/discard")
async def discard_drawn_card(
    slug: str,
    copy_id: int,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    copy = await get_drawn_copy(copy_id, deck.id, session)
    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    copy.zone = "deck"
    await reshuffle_remaining(deck.id, session)
    return await commit_and_serialize(character, deck, current_user, session)


@router.post("/characters/{slug}/deck/copies/{copy_id}/play")
async def play_drawn_card(
    slug: str,
    copy_id: int,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    copy = await get_drawn_copy(copy_id, deck.id, session)
    if copy.is_golden:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Golden cards cannot be played or destroyed")
    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    copy.zone = "destroyed"
    copy.shuffle_key = None
    await session.flush()
    deck.undo_copy_id = copy.id
    return await commit_and_serialize(character, deck, current_user, session)


@router.post("/characters/{slug}/deck/undo-play")
async def undo_last_play(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    if deck.undo_copy_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No played card can be restored")
    copy = await session.get(DeckCardCopy, deck.undo_copy_id)
    if copy is None or copy.zone != "destroyed":
        deck.undo_copy_id = None
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No played card can be restored")
    await claim_revision(deck, session)
    copy.zone = "drawn"
    copy.shuffle_key = None
    deck.undo_copy_id = None
    return await commit_and_serialize(character, deck, current_user, session)


@router.post("/characters/{slug}/deck/remove")
async def remove_card_copy(
    slug: str,
    body: DeckRemoveRequest,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)

    filters = [
        DeckCardDefinition.deck_id == deck.id,
        DeckCardDefinition.id == body.definitionId,
        DeckCardCopy.zone == "deck",
        DeckCardCopy.is_golden == body.isGolden,
    ]
    result = await session.execute(
        select(DeckCardCopy)
        .join(DeckCardDefinition, DeckCardDefinition.id == DeckCardCopy.definition_id)
        .where(*filters)
        .order_by(DeckCardCopy.id)
        .limit(1)
    )
    copy = result.scalar_one_or_none()
    if copy is None:
        raise HTTPException(status_code=404, detail="Card copy not found")

    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    await delete_copy_and_orphan_definition(copy, session)
    return await commit_and_serialize(character, deck, current_user, session)


@router.post("/characters/{slug}/deck/reset")
async def reset_deck(
    slug: str,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
):
    character, deck = await deck_context(slug, current_user, session)
    require_deck_manager(character, current_user)
    require_active_deck(deck)
    await claim_revision(deck, session)
    await finalize_undo(deck, session)
    result = await session.execute(
        select(DeckCardCopy)
        .join(DeckCardDefinition, DeckCardDefinition.id == DeckCardCopy.definition_id)
        .where(
            DeckCardDefinition.deck_id == deck.id,
            DeckCardCopy.zone.in_(("deck", "drawn")),
        )
    )
    for copy in result.scalars():
        copy.zone = "deck"
        copy.shuffle_key = next_shuffle_key()
    return await commit_and_serialize(character, deck, current_user, session)
