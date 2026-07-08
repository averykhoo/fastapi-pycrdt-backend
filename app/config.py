from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env")

    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def ystore_path(self) -> Path:
        return self.data_dir / "ystore.db"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
