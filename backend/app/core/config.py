from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "studyverify-backend"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    ENV: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
