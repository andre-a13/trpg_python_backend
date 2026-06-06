from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import USER_ROLE_ADMIN, USER_ROLE_PLAYER, create_password_hash, require_admin_user
from app.db import get_session
from app.models import Character, User


router = APIRouter()

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


def serialize_account(user: User, owned_character_count: int) -> AccountResponse:
    return AccountResponse(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        created_at=user.created_at,
        updated_at=user.updated_at,
        owned_character_count=owned_character_count,
    )


async def count_admins(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)).where(User.role == USER_ROLE_ADMIN))
    return result.scalar_one()


async def count_owned_characters(user_id: int, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(Character.id)).where(Character.owner_user_id == user_id)
    )
    return result.scalar_one()


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(User, func.count(Character.id))
        .outerjoin(Character, Character.owner_user_id == User.id)
        .group_by(User.id)
        .order_by(User.username)
    )
    return [serialize_account(user, owned_count) for user, owned_count in result.all()]


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(
    body: AccountCreate,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    existing = await session.execute(select(User.id).where(func.lower(User.username) == body.username).limit(1))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=body.username,
        password_hash=create_password_hash(body.password),
        role=body.role,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")

    await session.refresh(user)
    return serialize_account(user, 0)


@router.patch("/{user_id}", response_model=AccountResponse)
async def update_account(
    user_id: int,
    body: AccountUpdate,
    _current_admin: User = Depends(require_admin_user),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")

    data = body.model_dump(exclude_unset=True)
    if "role" in data and data["role"] is not None and data["role"] != user.role:
        if user.role == USER_ROLE_ADMIN and data["role"] != USER_ROLE_ADMIN:
            if await count_admins(session) <= 1:
                raise HTTPException(status_code=409, detail="Cannot demote the last admin")
        user.role = data["role"]

    await session.commit()
    await session.refresh(user)
    return serialize_account(user, await count_owned_characters(user.id, session))
