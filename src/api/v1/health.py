"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Health check")
async def health():
    return {"status": "ok", "service": "api_offer"}


@router.get("/ready", summary="Readiness check")
async def ready():
    return {"status": "ready"}
