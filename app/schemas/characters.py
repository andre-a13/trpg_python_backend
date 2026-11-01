from typing import Annotated
from annotated_types import Ge
from pydantic import BaseModel, Field, HttpUrl, StringConstraints


SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
InventoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
InventoryNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
NoteTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
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
    ownerUserId: int | None = None


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
    ownerUserId: int | None = None


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


class CharacterNoteCreate(BaseModel):
    title: NoteTitle
    content: str | None = ""


class CharacterNoteUpdate(BaseModel):
    title: NoteTitle | None = None
    content: str | None = None
    sortOrder: Annotated[int, Ge(0)] | None = None


class ReorderEntry(BaseModel):
    id: int
    sortOrder: Annotated[int, Ge(0)]


class ReorderRequest(BaseModel):
    items: list[ReorderEntry]

class CharacterTeamResponse(BaseModel):
    uuid: str
    name: str
    illustrationUrl: str | None


class CharacterNoteResponse(BaseModel):
    id: int
    characterId: int
    title: str
    content: str
    sortOrder: int


class InventoryContentResponse(BaseModel):
    id: int
    categoryId: int
    name: str
    quantity: int
    notes: str | None
    sortOrder: int


class InventoryCategoryResponse(BaseModel):
    id: int
    characterId: int
    name: str
    sortOrder: int
    contents: list[InventoryContentResponse]


class HearthstomancerStatusResponse(BaseModel):
    configured: bool
    enabled: bool


class CharacterCreatedResponse(BaseModel):
    id: int
    name: str
    slug: str
    ownerUserId: int | None


class CharacterSummaryResponse(BaseModel):
    id: int
    slug: str
    name: str
    race: str
    portraitUrl: str | None
    backgroundUrl: str | None
    ownerUserId: int | None
    ownerUsername: str | None
    stats: SkillSet
    skillsPrimary: list[str]
    skillsSecondary: list[str]
    inventory: list[str]
    gold: int
    notes: str | None
    current_hp: int
    bonusHealth: int
    invengineerEnabled: bool
    hearthstomancer: HearthstomancerStatusResponse
    teams: list[CharacterTeamResponse]


class CharacterDetailResponse(CharacterSummaryResponse):
    inventoryCategories: list[InventoryCategoryResponse]
    noteTabs: list[CharacterNoteResponse]
