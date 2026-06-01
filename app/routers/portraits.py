from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_current_user
from app.db import get_session
from app.models import Character, User
from app.schemas.uploads import CharacterPortraitUploadRequest, CharacterPortraitUploadResponse
from app.storage.scaleway import (
    ScalewayObjectStorage,
    StorageConfigurationError,
    UploadValidationError,
    get_object_storage,
)

router = APIRouter()


@router.post("/{slug}/portrait-upload", response_model=CharacterPortraitUploadResponse)
async def create_character_portrait_upload(
    slug: str,
    body: CharacterPortraitUploadRequest,
    _current_user: User = Depends(require_current_user),
    session: AsyncSession = Depends(get_session),
    storage: ScalewayObjectStorage = Depends(get_object_storage),
):
    result = await session.execute(select(Character.id).where(Character.slug == slug).limit(1))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Character not found")

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
