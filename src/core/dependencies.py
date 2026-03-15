"""Dependency injection for api_offer."""

from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.session import get_db

# -- DB session dependency --
DbSession = Annotated[AsyncSession, Depends(get_db)]

# -- Admin API Key auth --
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_admin(api_key: str | None = Depends(_API_KEY_HEADER)) -> str:
    if not api_key or api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida o ausente")
    return api_key


AdminAuth = Annotated[str, Depends(require_admin)]
