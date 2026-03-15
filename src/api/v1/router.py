"""API v1 router — aggregates all sub-routers."""

from fastapi import APIRouter

from src.api.v1 import health, ofertas, evolucion

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(ofertas.router)
api_router.include_router(evolucion.router)
