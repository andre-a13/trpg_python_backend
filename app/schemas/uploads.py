from typing import Literal

from pydantic import BaseModel, Field


AllowedImageContentType = Literal["image/jpeg", "image/png", "image/webp"]


class CharacterPortraitUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: AllowedImageContentType
    size: int = Field(gt=0)


class CharacterPortraitUploadResponse(BaseModel):
    upload_url: str
    object_key: str
    public_url: str
    expires_in: int


class CharacterBackgroundUploadRequest(CharacterPortraitUploadRequest):
    pass


class CharacterBackgroundUploadResponse(CharacterPortraitUploadResponse):
    pass


class TeamIllustrationUploadRequest(CharacterPortraitUploadRequest):
    pass


class TeamIllustrationUploadResponse(CharacterPortraitUploadResponse):
    pass
