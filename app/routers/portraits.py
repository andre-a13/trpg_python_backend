from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin, require_current_user
from app.db import get_session
from app.models import Character, User
from app.schemas.uploads import (
    CharacterBackgroundUploadRequest,
    CharacterBackgroundUploadResponse,
    CharacterPortraitUploadRequest,
    CharacterPortraitUploadResponse,
)
from app.storage.scaleway import (
    ScalewayObjectStorage,
    StorageConfigurationError,
    UploadValidationError,
    get_object_storage,
)

router = APIRouter()


async def get_writable_character_or_404(slug: str, current_user: User, session: AsyncSession) -> Character:
    result = await session.execute(select(Character).where(Character.slug == slug).limit(1))
    character = result.scalar_one_or_none()
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    if not is_admin(current_user) and character.owner_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Character write access required")
    return character


@router.post("/{slug}/portrait-upload", response_model=CharacterPortraitUploadResponse)
async def create_character_portrait_upload(
    slug: str,
    body: CharacterPortraitUploadRequest,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
    storage: ScalewayObjectStorage = Depends(get_object_storage),
):
    await get_writable_character_or_404(slug, current_user, session)

    try:
        storage.validate_character_portrait(body.content_type, body.size)
        object_key = storage.create_character_portrait_key(slug, body.content_type)
        upload_url = storage.create_presigned_put_url(object_key, body.content_type)
        public_url = storage.public_url(object_key)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CharacterPortraitUploadResponse(
        upload_url=upload_url,
        object_key=object_key,
        public_url=public_url,
        expires_in=storage.settings.character_image_upload_url_expires_seconds,
    )


@router.post("/{slug}/background-upload", response_model=CharacterBackgroundUploadResponse)
async def create_character_background_upload(
    slug: str,
    body: CharacterBackgroundUploadRequest,
    current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
    storage: ScalewayObjectStorage = Depends(get_object_storage),
):
    await get_writable_character_or_404(slug, current_user, session)

    try:
        storage.validate_character_background(body.content_type, body.size)
        object_key = storage.create_character_background_key(slug, body.content_type)
        upload_url = storage.create_presigned_put_url(object_key, body.content_type)
        public_url = storage.public_url(object_key)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CharacterBackgroundUploadResponse(
        upload_url=upload_url,
        object_key=object_key,
        public_url=public_url,
        expires_in=storage.settings.character_image_upload_url_expires_seconds,
    )
