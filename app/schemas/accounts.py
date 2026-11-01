from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, StringConstraints, field_validator

USER_ROLE_PLAYER = "player"

Username = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=1024)]
UserRole = Literal["admin", "player"]


class AccountCreate(BaseModel):
    username: Username
    password: Password
    role: UserRole = USER_ROLE_PLAYER

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.casefold()


class AccountUpdate(BaseModel):
    role: UserRole | None = None


class AccountResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    created_at: datetime
    updated_at: datetime
    owned_character_count: int

