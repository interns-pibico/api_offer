"""API v1 router — aggregates all sub-routers."""

from fastapi import APIRouter

from src.api.v1 import auth, health, lists, ofertas, evolucion, flyers, shopping

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(lists.router)
api_router.include_router(ofertas.router)
api_router.include_router(evolucion.router)
api_router.include_router(flyers.router)
api_router.include_router(shopping.router)
