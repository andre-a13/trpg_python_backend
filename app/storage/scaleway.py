from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import uuid4

from app.config import Settings, get_settings


ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class StorageConfigurationError(RuntimeError):
    pass


class UploadValidationError(ValueError):
    pass


class ScalewayObjectStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_character_portrait(self, content_type: str, size: int) -> None:
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_CONTENT_TYPES))
            raise UploadValidationError(f"Unsupported image type. Allowed types: {allowed}")
        if size > self.settings.character_image_max_size_bytes:
            raise UploadValidationError(
                f"Image is too large. Max size is {self.settings.character_image_max_size_mb} MB"
            )

    def create_character_portrait_key(self, character_slug: str, content_type: str) -> str:
        extension = ALLOWED_IMAGE_CONTENT_TYPES[content_type]
        filename = f"{uuid4().hex}{extension}"
        return str(PurePosixPath("characters", character_slug, "portrait", filename))

    def create_presigned_put_url(self, object_key: str, content_type: str) -> str:
        client = self._client()
        return client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket_name(),
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=self.settings.character_image_upload_url_expires_seconds,
        )

    def public_url(self, object_key: str) -> str:
        if self.settings.scw_public_bucket_url:
            base_url = self.settings.scw_public_bucket_url.rstrip("/")
        else:
            bucket = self._bucket_name()
            base_url = f"https://{bucket}.s3.{self.settings.scw_object_storage_region}.scw.cloud"
        return f"{base_url}/{quote(object_key)}"

    def upload_file(
        self,
        file_path: Path,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        client = self._client()
        client.upload_file(
            str(file_path),
            self._bucket_name(),
            object_key,
            ExtraArgs={"ContentType": content_type},
        )

    def _bucket_name(self) -> str:
        if not self.settings.scw_object_storage_bucket:
            raise StorageConfigurationError("SCW_OBJECT_STORAGE_BUCKET is not configured")
        return self.settings.scw_object_storage_bucket

    def _client(self):
        if not self.settings.scw_access_key or not self.settings.scw_secret_key:
            raise StorageConfigurationError("Scaleway object storage credentials are not configured")

        try:
            import boto3
        except ImportError as exc:
            raise StorageConfigurationError("boto3 is required for Scaleway object storage") from exc

        return boto3.client(
            "s3",
            endpoint_url=self.settings.scw_endpoint_url,
            aws_access_key_id=self.settings.scw_access_key,
            aws_secret_access_key=self.settings.scw_secret_key,
            region_name=self.settings.scw_object_storage_region,
        )


def get_object_storage() -> ScalewayObjectStorage:
    return ScalewayObjectStorage(get_settings())
