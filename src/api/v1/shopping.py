"""Shopping list endpoint — NL prompt → ingredients → best offers."""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.core.config import settings
from src.core.exceptions import BadRequestException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shopping", tags=["shopping"])

# Rate limit: 10 generations per hour per IP
_RATE_LIMIT = 10
_RATE_WINDOW = 3600  # seconds


class ShoppingRequest(BaseModel):
    prompt: str


async def _check_rate_limit(request: Request) -> None:
    """Simple Redis-based rate limiter: 10 requests/hour per IP."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"shopping_rl:{client_ip}"
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _RATE_WINDOW)
        await r.aclose()
        if count > _RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Límite de {_RATE_LIMIT} generaciones por hora alcanzado. Inténtalo más tarde.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Rate limit check failed (allowing request): %s", exc)


@router.post("/generate", summary="Generate shopping list from NL prompt")
async def generate_shopping_list(body: ShoppingRequest, request: Request) -> dict:
    """Given a natural language prompt (e.g. 'Cena para 4, pasta con verduras'),
    generate an ingredient list and find the best offers across supermarkets."""
    from src.services.shopping_service import generate_shopping_list as _generate

    await _check_rate_limit(request)

    if len(body.prompt) < 3:
        raise BadRequestException(detail="El prompt es demasiado corto")
    if len(body.prompt) > 500:
        raise BadRequestException(detail="El prompt es demasiado largo (max 500 chars)")

    try:
        result = await _generate(body.prompt)
    except ValueError as e:
        raise BadRequestException(detail=str(e))
    except Exception as exc:
        logger.error("Shopping list generation failed: %s", exc)
        raise BadRequestException(detail="Error al generar la lista. Inténtalo de nuevo.")

    return result
