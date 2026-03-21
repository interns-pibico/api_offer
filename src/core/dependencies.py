"""Dependency injection for api_offer."""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.security import decode_token
from src.db.session import get_db
from src.models.user import User

# -- DB session dependency --
DbSession = Annotated[AsyncSession, Depends(get_db)]

# -- Admin API Key auth --
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_admin(api_key: str | None = Depends(_API_KEY_HEADER)) -> str:
    if not api_key or api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida o ausente")
    return api_key


AdminAuth = Annotated[str, Depends(require_admin)]

# -- Optional user auth (JWT) --
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


async def get_current_user_optional(
    token: str | None = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Returns User if logged in, None if not. Never raises."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        return None
    try:
        user_id = int(user_id_raw)
    except (ValueError, TypeError):
        return None
    user = await db.get(User, user_id)
    return user if user and user.is_active else None


async def get_current_user_required(
    token: str | None = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Returns User or raises 401."""
    user = await get_current_user_optional(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
CurrentUser = Annotated[User, Depends(get_current_user_required)]
