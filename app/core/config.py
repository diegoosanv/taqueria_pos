import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Taqueria Financial Layer"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "sqlite:///./taqueria.db"
    GEMINI_API_KEY: str = ""

    META_VERIFY_TOKEN: str = "taqueria_webhook_secret_token_2026"
    META_ACCESS_TOKEN: str = ""
    META_PHONE_NUMBER_ID: str = ""

    AUTHORIZED_PHONES: str = ""

    @property
    def authorized_phone_list(self) -> List[str]:
        if not self.AUTHORIZED_PHONES:
            return []
        return [p.strip() for p in self.AUTHORIZED_PHONES.split(",") if p.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
