"""Application configuration via pydantic-settings."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure AD - defaults to Azure CLI public client ID (works with personal accounts)
    azure_client_id: str = "04b07795-a71b-4346-935f-02f9a1efa4ce"

    # Email
    outlook_email: str = "dannewman70@outlook.com"

    # Archive location
    archive_dir: Path = Field(
        default_factory=lambda: Path.home() / ".newsletter-archive"
    )

    # Fetching defaults
    default_days_back: int = 7
    batch_size: int = 50

    @property
    def data_dir(self) -> Path:
        return self.archive_dir / "data"

    @property
    def archives_dir(self) -> Path:
        return self.data_dir / "archives"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "newsletters.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def token_path(self) -> Path:
        return self.archive_dir / "msal_token_cache.json"

    @property
    def is_configured(self) -> bool:
        return bool(self.azure_client_id)

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
