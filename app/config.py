from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/data.db"
    cors_origins: str = (
        "https://www.arnaud-a.dev,"
        "https://arnaud-a.dev,"
        "https://game.arnaud-a.dev,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173"
    )
    scw_access_key: str | None = None
    scw_secret_key: str | None = None
    scw_object_storage_bucket: str | None = None
    scw_object_storage_region: str = "fr-par"
    scw_object_storage_endpoint: str | None = None
    scw_public_bucket_url: str | None = None
    db_snapshot_on_shutdown: bool = True
    db_snapshot_prefix: str = "save"
    character_image_max_size_mb: int = Field(default=5, gt=0)
    character_background_image_max_size_mb: int = Field(default=15, gt=0)
    team_image_max_size_mb: int = Field(default=15, gt=0)
    character_image_upload_url_expires_seconds: int = Field(default=900, gt=0)
    auth_token_secret: str | None = None
    access_token_expires_seconds: int = Field(default=3600, gt=0)
    refresh_token_expires_seconds: int = Field(default=2592000, gt=0)
    refresh_token_cookie_name: str = "trpg_refresh_token"
    refresh_token_cookie_secure: bool = True
    refresh_token_cookie_samesite: str = "lax"
    allow_first_user_registration: bool = True

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

    @field_validator("refresh_token_cookie_samesite")
    @classmethod
    def validate_refresh_token_cookie_samesite(cls, value):
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("refresh_token_cookie_samesite must be lax, strict, or none")
        return normalized

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

    @property
    def character_background_image_max_size_bytes(self) -> int:
        return self.character_background_image_max_size_mb * 1024 * 1024

    @property
    def team_image_max_size_bytes(self) -> int:
        return self.team_image_max_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
