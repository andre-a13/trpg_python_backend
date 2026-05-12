from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/data.db"
    cors_origins: str = (
        "https://www.arnaud-a.dev,"
        "https://arnaud-a.dev,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )
    scw_access_key: str | None = None
    scw_secret_key: str | None = None
    scw_object_storage_bucket: str | None = None
    scw_object_storage_region: str = "fr-par"
    scw_object_storage_endpoint: str | None = None
    scw_public_bucket_url: str | None = None
    character_image_max_size_mb: int = Field(default=5, gt=0)
    character_image_upload_url_expires_seconds: int = Field(default=900, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value):
        if not [origin.strip() for origin in value.split(",") if origin.strip()]:
            raise ValueError("cors_origins must contain at least one origin")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def scw_endpoint_url(self) -> str:
        if self.scw_object_storage_endpoint:
            return self.scw_object_storage_endpoint.rstrip("/")
        return f"https://s3.{self.scw_object_storage_region}.scw.cloud"

    @property
    def character_image_max_size_bytes(self) -> int:
        return self.character_image_max_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
