"""api_offer — FastAPI application entry point."""

import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.v1.router import api_router
from src.core.config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run stale-offer cleanup on startup so expired offers are hidden immediately."""
    from src.services.oferta_service import run_stale_cleanup_background
    try:
        await run_stale_cleanup_background()
        logger.info("Startup stale-offer cleanup completed")
    except Exception as exc:
        logger.warning("Startup stale-offer cleanup failed (non-fatal): %s", exc)
    yield


app = FastAPI(
    title="API Offer",
    description="API de ofertas y promociones de supermercados",
    version="1.0.0",
    root_path=settings.ROOT_PATH,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://raquel.pibico.es",
        "http://localhost:6958",
        "http://127.0.0.1:6956",  # api_label integration
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "Accept"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(api_router)


# ---------------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Landing page with hero + stats."""
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "root_path": settings.ROOT_PATH},
    )


@app.get("/ofertas", response_class=HTMLResponse)
async def ofertas_page(request: Request):
    """Ofertas dashboard with grid + filters."""
    return templates.TemplateResponse(
        "ofertas.html",
        {"request": request, "root_path": settings.ROOT_PATH},
    )


@app.get("/comparar", response_class=HTMLResponse, include_in_schema=False)
async def comparar_page(request: Request):
    """Price comparator page."""
    return templates.TemplateResponse(
        "comparar.html",
        {"request": request, "root_path": settings.ROOT_PATH},
    )


@app.get("/evolucion", response_class=HTMLResponse, include_in_schema=False)
async def evolucion_page(request: Request):
    """Price evolution charts page."""
    return templates.TemplateResponse(
        "evolucion.html",
        {"request": request, "root_path": settings.ROOT_PATH},
    )


@app.get("/folletos", response_class=HTMLResponse, include_in_schema=False)
async def folletos_page(request: Request):
    """Flyer extraction tool (admin)."""
    return templates.TemplateResponse(
        "folletos.html",
        {"request": request, "root_path": settings.ROOT_PATH},
    )


@app.get("/legal", response_class=HTMLResponse, include_in_schema=False)
async def legal_page(request: Request):
    """Legal notice, terms of service and privacy policy."""
    return templates.TemplateResponse(
        "legal.html",
        {"request": request, "root_path": settings.ROOT_PATH, "active_page": "legal"},
    )
