from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "api_offer"
    DEBUG: bool = False
    ROOT_PATH: str = "/offer"

    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/api_offer_psql"
    REDIS_URL: str = "redis://localhost:6379/4"

    ADMIN_API_KEY: str = "change-me-in-production"
    LABEL_API_URL: str = "http://127.0.0.1:6956"

    # Offers older than this many hours are automatically marked inactive
    OFFER_STALE_HOURS: int = 48

    # OpenAI (flyer extraction)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-mini"
    OPENAI_MAX_TOKENS: int = 8192
    FLYER_MAX_FILE_SIZE_MB: int = 50
    FLYER_DPI: int = 200

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
