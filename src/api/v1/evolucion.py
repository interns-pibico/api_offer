from typing import Optional

from fastapi import APIRouter, Query

from src.core.dependencies import DbSession
from src.services import oferta_service

router = APIRouter(prefix="/evolucion", tags=["evolucion"])


@router.get("/snapshots")
async def get_snapshots(
    db: DbSession,
    days: int = Query(default=7, ge=1, le=90),
    fuente: Optional[str] = Query(default=None),
):
    return await oferta_service.get_evolucion(db, days=days, fuente=fuente)
