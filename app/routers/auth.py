from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_password_hash,
    create_refresh_token,
    hash_refresh_token,
    require_current_user,
    verify_password,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models import RefreshToken, User


router = APIRouter()
optional_security = HTTPBearer(auto_error=False)

Username = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class AccountCredentials(BaseModel):
    username: Username
    password: Password


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    username: str
    created_at: datetime
    updated_at: datetime


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def issue_token_pair(
    user: User,
    settings: Settings,
    session: AsyncSession,
) -> TokenPairResponse:
    access_token, expires_in = create_access_token(user, settings)
    refresh_token, refresh_record = create_refresh_token(settings)
    refresh_record.user_id = user.id
    session.add(refresh_record)
    await session.commit()
    return TokenPairResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        refresh_expires_in=settings.refresh_token_expires_seconds,
    )


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)))
    return result.scalar_one()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: AccountCredentials,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    if await count_users(session) > 0:
        await require_current_user(credentials, settings, session)

    existing = await session.execute(select(User.id).where(User.username == body.username).limit(1))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=body.username,
        password_hash=create_password_hash(body.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")

    await session.refresh(user)
    return serialize_user(user)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: AccountCredentials,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(User).where(User.username == body.username).limit(1))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await issue_token_pair(user, settings, session)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    body: RefreshTokenRequest,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
    )
    refresh_record = result.scalar_one_or_none()
    if (
        refresh_record is None
        or refresh_record.revoked_at is not None
        or refresh_record.expires_at <= datetime.utcnow()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = await session.get(User, refresh_record.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    access_token, expires_in = create_access_token(user, settings)
    new_refresh_token, new_refresh_record = create_refresh_token(settings)
    new_refresh_record.user_id = user.id
    session.add(new_refresh_record)
    await session.flush()

    refresh_record.revoked_at = datetime.utcnow()
    refresh_record.replaced_by_token_id = new_refresh_record.id
    await session.commit()

    return TokenPairResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=expires_in,
        refresh_expires_in=settings.refresh_token_expires_seconds,
    )


@router.post("/logout", status_code=204)
async def logout(
    body: RefreshTokenRequest,
    session: AsyncSession = Depends(get_session),
):
    token_hash = hash_refresh_token(body.refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
    )
    refresh_record = result.scalar_one_or_none()
    if refresh_record is not None and refresh_record.revoked_at is None:
        refresh_record.revoked_at = datetime.utcnow()
        await session.commit()
    return None


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(require_current_user)):
    return serialize_user(current_user)
