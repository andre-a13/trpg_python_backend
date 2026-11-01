from typing import Annotated
from uuid import UUID
from pydantic import BaseModel, HttpUrl, StringConstraints


TeamName = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]


class TeamCreate(BaseModel):
    uuid: UUID | None = None
    name: TeamName
    illustrationUrl: HttpUrl | None = None


class TeamUpdate(BaseModel):
    name: TeamName | None = None
    illustrationUrl: HttpUrl | None = None


class TeamIllustrationUpdate(BaseModel):
    illustrationUrl: HttpUrl | None = None

class TeamCharacterResponse(BaseModel):
    id: int
    slug: str
    name: str
    race: str
    portraitUrl: str | None
    ownerUserId: int | None


class TeamResponse(BaseModel):
    uuid: str
    name: str
    illustrationUrl: str | None
    characters: list[TeamCharacterResponse]
