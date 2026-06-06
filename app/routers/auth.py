from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, StringConstraints, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    USER_ROLE_ADMIN,
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

Username = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=1024)]

AUTH_RATE_LIMIT_WINDOW_SECONDS = 300
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 5
_auth_attempts: dict[str, list[float]] = {}


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
    role: str
    created_at: datetime
    updated_at: datetime


class TokenPairResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_in: int


def serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def issue_token_pair(
    user: User,
    settings: Settings,
    session: AsyncSession,
    response: Response,
) -> TokenPairResponse:
    access_token, expires_in = create_access_token(user, settings)
    refresh_token, refresh_record = create_refresh_token(settings)
    refresh_record.user_id = user.id
    session.add(refresh_record)
    await session.commit()
    set_refresh_token_cookie(response, refresh_token, settings)
    return TokenPairResponse(
        access_token=access_token,
        expires_in=expires_in,
        refresh_expires_in=settings.refresh_token_expires_seconds,
    )


async def count_users(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(User.id)))
    return result.scalar_one()


def set_refresh_token_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=token,
        max_age=settings.refresh_token_expires_seconds,
        httponly=True,
        secure=settings.refresh_token_cookie_secure,
        samesite=settings.refresh_token_cookie_samesite,
        path="/auth",
    )


def clear_refresh_token_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_token_cookie_name,
        httponly=True,
        secure=settings.refresh_token_cookie_secure,
        samesite=settings.refresh_token_cookie_samesite,
        path="/auth",
    )


def get_refresh_token_from_cookie(request: Request, settings: Settings) -> str:
    token = request.cookies.get(settings.refresh_token_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return token


def _auth_rate_limit_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{username}"


def check_auth_rate_limit(request: Request, username: str) -> str:
    now = datetime.utcnow().timestamp()
    key = _auth_rate_limit_key(request, username)
    attempts = [
        attempt
        for attempt in _auth_attempts.get(key, [])
        if now - attempt < AUTH_RATE_LIMIT_WINDOW_SECONDS
    ]
    _auth_attempts[key] = attempts
    if len(attempts) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many authentication attempts")
    return key


def record_auth_failure(key: str) -> None:
    _auth_attempts.setdefault(key, []).append(datetime.utcnow().timestamp())


def clear_auth_failures(key: str) -> None:
    _auth_attempts.pop(key, None)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: AccountCredentials,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    rate_limit_key = check_auth_rate_limit(request, body.username)
    users_count = await count_users(session)
    if users_count > 0:
        record_auth_failure(rate_limit_key)
        raise HTTPException(status_code=403, detail="Initial account already exists")
    elif not settings.allow_first_user_registration:
        record_auth_failure(rate_limit_key)
        raise HTTPException(status_code=403, detail="Initial account registration is disabled")

    existing = await session.execute(select(User.id).where(func.lower(User.username) == body.username).limit(1))
    if existing.scalar_one_or_none() is not None:
        record_auth_failure(rate_limit_key)
        raise HTTPException(status_code=409, detail="Username already exists")

    user = User(
        username=body.username,
        password_hash=create_password_hash(body.password),
        role=USER_ROLE_ADMIN,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        record_auth_failure(rate_limit_key)
        raise HTTPException(status_code=409, detail="Username already exists")

    await session.refresh(user)
    clear_auth_failures(rate_limit_key)
    return serialize_user(user)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: AccountCredentials,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    rate_limit_key = check_auth_rate_limit(request, body.username)
    result = await session.execute(select(User).where(func.lower(User.username) == body.username).limit(1))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        record_auth_failure(rate_limit_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    clear_auth_failures(rate_limit_key)
    return await issue_token_pair(user, settings, session, response)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    token_hash = hash_refresh_token(get_refresh_token_from_cookie(request, settings))
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
    set_refresh_token_cookie(response, new_refresh_token, settings)

    return TokenPairResponse(
        access_token=access_token,
        expires_in=expires_in,
        refresh_expires_in=settings.refresh_token_expires_seconds,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
):
    refresh_token = request.cookies.get(settings.refresh_token_cookie_name)
    if not refresh_token:
        clear_refresh_token_cookie(response, settings)
        return None

    token_hash = hash_refresh_token(refresh_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).limit(1)
    )
    refresh_record = result.scalar_one_or_none()
    if refresh_record is not None and refresh_record.revoked_at is None:
        refresh_record.revoked_at = datetime.utcnow()
        await session.commit()
    clear_refresh_token_cookie(response, settings)
    return None


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(require_current_user)):
    return serialize_user(current_user)
