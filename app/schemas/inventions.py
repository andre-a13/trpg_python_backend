from typing import Annotated

from pydantic import BaseModel, StringConstraints


class InventionCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class InvengineerUpdate(BaseModel):
    enabled: bool


class InventionResponse(BaseModel):
    id: int
    name: str
    description: str


class InventionPermissions(BaseModel):
    canDraw: bool


class InventionStateResponse(BaseModel):
    enabled: bool
    drawCount: int
    permissions: InventionPermissions
    items: list[InventionResponse]


class InvengineerStatusResponse(BaseModel):
    enabled: bool
