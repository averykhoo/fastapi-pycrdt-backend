"""Application configuration, loaded from environment variables / `.env`.

All settings are prefixed `APP_` (e.g. `APP_DATA_DIR=/srv/data`), which lets
the test suite point a subprocess server at an isolated `tmp_path` via
`APP_DATA_DIR` without touching the developer's real `data/` directory.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the app.

    Attributes:
        data_dir: Root directory for all persisted state (SQLite databases,
            uploaded audio files). Created on import if missing.
    """

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env")

    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        """Path to the SQLModel application database (documents, activity,
        experiments — everything except the CRDT update log)."""
        return self.data_dir / "app.db"

    @property
    def ystore_path(self) -> Path:
        """Path to the SQLite YStore database that persists Yjs document
        update history, keyed by room name."""
        return self.data_dir / "ystore.db"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
