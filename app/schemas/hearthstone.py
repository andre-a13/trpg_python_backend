from typing import Annotated, Literal
from pydantic import BaseModel, Field, HttpUrl, StringConstraints


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

class CardFields(BaseModel):
    name: str
    cost: int | None
    attack: int | None
    health: int | None
    durability: int | None
    text: str
    cardType: str | None
    rarity: str | None
    cardClass: str | None
    tribe: str | None
    spellSchool: str | None
    cardSet: str | None


class HearthstoneCardResponse(CardFields):
    id: str
    cardSetName: str
    illustrationUrl: str
    renderUrl: str


class HearthstoneSetResponse(BaseModel):
    code: str
    name: str
    cardCount: int


class HearthstoneCatalogResponse(BaseModel):
    items: list[HearthstoneCardResponse]
    sets: list[HearthstoneSetResponse]
    page: int
    pageSize: int
    total: int


class HearthstonePackResponse(BaseModel):
    cardSet: str
    cards: list[HearthstoneCardResponse]


class DeckDefinitionResponse(CardFields):
    id: int
    sourceCardId: str | None
    illustrationUrl: str | None
    originalIllustrationUrl: str | None
    renderUrl: str | None
    isVariant: bool
    normalCount: int
    goldenCount: int
    remainingNormalCount: int
    remainingGoldenCount: int


class DeckCopyResponse(BaseModel):
    copyId: int
    isGolden: bool
    definition: DeckDefinitionResponse


class DeckPermissions(BaseModel):
    canManage: bool
    canActivate: bool


class DeckCounts(BaseModel):
    total: int
    remaining: int
    drawn: int


class DeckStateResponse(BaseModel):
    configured: Literal[True]
    enabled: bool
    revision: int
    permissions: DeckPermissions
    counts: DeckCounts
    definitions: list[DeckDefinitionResponse]
    drawnCards: list[DeckCopyResponse]
    undoablePlay: DeckCopyResponse | None


class DeckUnconfiguredResponse(BaseModel):
    configured: Literal[False]
    enabled: Literal[False]


class DeckImportFileRequest(BaseModel):
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    contentBase64: Annotated[str, StringConstraints(min_length=1, max_length=2796204)]


class DeckImportSourceRow(BaseModel):
    rowNumber: Annotated[int, Field(ge=1, le=1000)]
    name: CardName
    quantity: Annotated[int, Field(ge=1, le=500)] = 1
    isGolden: bool = False
    cardType: CardMetadata | None = None
    cost: Annotated[int, Field(ge=0, le=10000)] | None = None
    attack: Annotated[int, Field(ge=0, le=10000)] | None = None
    health: Annotated[int, Field(ge=0, le=10000)] | None = None
    text: CardText | None = None
    illustrationUrl: HttpUrl | None = None


class DeckImportPreviewRow(BaseModel):
    rowNumber: int
    source: DeckImportSourceRow | None
    rawName: str
    rawValues: list[str]
    status: Literal["matched", "suggested", "missing", "invalid"]
    candidates: list[HearthstoneCardResponse]
    selectedCardId: str | None
    error: str | None = None


class DeckImportPreviewResponse(BaseModel):
    revision: int
    rows: list[DeckImportPreviewRow]
    totalCount: int
    goldenCount: int


class DeckImportSelection(BaseModel):
    source: DeckImportSourceRow
    sourceCardId: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class DeckImportCommitRequest(BaseModel):
    expectedRevision: NonNegative
    selections: list[DeckImportSelection] = Field(min_length=1, max_length=500)
