from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class LightWordCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class LightWordResponse(BaseModel):
    id: int
    name: str
    description: str


class LightBookSettingsUpdate(BaseModel):
    slotCount: Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class LightBookSettingsResponse(BaseModel):
    slotCount: int


class LightBookResponse(BaseModel):
    slotCount: Annotated[int | None, Field(description="Null when the collection is private")]
    words: list[LightWordResponse]
