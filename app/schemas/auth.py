from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

UserRole = Literal["admin", "player"]
Username = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=1024)]


class AccountCredentials(BaseModel):
    username: Username
    password: Password

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.casefold()


class UserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    created_at: datetime
    updated_at: datetime


class TokenPairResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int
