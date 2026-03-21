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
    OPENAI_MAX_TOKENS: int = 4096
    FLYER_MAX_FILE_SIZE_MB: int = 50
    FLYER_DPI: int = 150
    FLYER_IMAGE_DETAIL: str = "auto"  # "low" = 85 tokens/img, "high" = ~600, "auto" = OpenAI decides

    # Groq (shopping list generation — free tier, separate from OpenAI)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # JWT (optional user auth)
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
