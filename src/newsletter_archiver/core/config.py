"""Application configuration via pydantic-settings."""

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure AD - defaults to Microsoft Graph CLI public client ID
    azure_client_id: str = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

    # Email
    outlook_email: str = "dannewman70@outlook.com"

    # Archive files location (backed up via Proton Drive)
    archive_dir: Path = Field(
        default_factory=lambda: Path("/mnt/c/Users/danne/Proton Drive/noomonics/My files/Projects/newsletter-archive")
    )

    # Local data directory (SQLite DB and auth tokens — not cloud-synced)
    local_dir: Path = Field(
        default_factory=lambda: Path.home() / ".newsletter-archive"
    )

    # Fetching defaults
    default_days_back: int = 7
    batch_size: int = 100

    @property
    def archives_dir(self) -> Path:
        return self.archive_dir / "archives"

    @property
    def db_path(self) -> Path:
        return self.local_dir / "data" / "newsletters.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def token_path(self) -> Path:
        return self.local_dir / "msal_token_cache.json"

    @property
    def publications_path(self) -> Path:
        return self.local_dir / "publications.yaml"

    def load_publications(self) -> dict[str, str]:
        """Load email → publication name mapping from YAML file.

        Returns empty dict if file doesn't exist.
        """
        if not self.publications_path.exists():
            return {}
        with open(self.publications_path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

    @property
    def is_configured(self) -> bool:
        return bool(self.azure_client_id)

    def ensure_dirs(self) -> None:
        """Create all required directories."""
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
