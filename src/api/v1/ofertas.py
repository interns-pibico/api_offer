"""Ofertas endpoints — public queries + admin scrape/delete."""

import logging
import math

from fastapi import APIRouter, BackgroundTasks, Query

from src.core.dependencies import AdminAuth, DbSession
from src.core.exceptions import NotFoundException
from src.schemas.oferta import CompareResponse, OfertaResponse, ScrapeResponse
from src.schemas.pagination import PaginatedResponse
from src.services import oferta_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/offers", tags=["ofertas"])


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=PaginatedResponse[OfertaResponse],
    summary="List offers",
)
async def list_ofertas(
    db: DbSession,
    fuente: str | None = Query(default=None, description="Filter by source domain"),
    barcode: str | None = Query(default=None, description="Filter by EAN barcode"),
    q: str | None = Query(default=None, description="Search by product name"),
    activo: bool | None = Query(default=True, description="Filter by active status"),
    sort: str = Query(default="descuento_desc", description="Sort: descuento_desc|precio_asc|precio_desc|fecha_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> PaginatedResponse[OfertaResponse]:
    """List scraped price-drop offers with optional filters. Public endpoint."""
    offset = (page - 1) * page_size
    items, total = await oferta_service.list_ofertas(
        db, fuente=fuente, activo=activo, barcode=barcode, q=q, sort=sort, offset=offset, limit=page_size
    )
    pages = math.ceil(total / page_size) if total > 0 else 1
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size, pages=pages
    )


@router.get(
    "/fuentes",
    response_model=list[str],
    summary="List all distinct sources",
)
async def list_fuentes(db: DbSession) -> list[str]:
    """Return all distinct fuente values present in the offers table."""
    return await oferta_service.list_fuentes(db)


@router.get(
    "/barcode/{ean}",
    response_model=list[OfertaResponse],
    summary="Get offers by EAN barcode",
)
async def get_offers_by_barcode(
    ean: str,
    db: DbSession,
) -> list[OfertaResponse]:
    """Return all active offers matching an EAN barcode. Used by api_label integration."""
    return await oferta_service.get_ofertas_by_barcode(ean, db)


@router.get(
    "/compare",
    response_model=CompareResponse,
    summary="Compare product across supermarkets",
)
async def compare_offers(
    db: DbSession,
    q: str = Query(..., min_length=2, description="Product name to search"),
    limit: int = Query(default=40, ge=1, le=100),
) -> CompareResponse:
    """Search all active offers matching q, ordered by price ASC. First result is the best deal."""
    result = await oferta_service.compare_product(q, db, limit)
    return CompareResponse(**result)


@router.get(
    "/stats",
    summary="Get offer statistics",
)
async def get_stats(db: DbSession) -> dict:
    """Return aggregate statistics about active offers."""
    return await oferta_service.get_stats(db)


@router.get(
    "/{oferta_id}",
    response_model=OfertaResponse,
    summary="Get a single offer by ID",
)
async def get_oferta(
    oferta_id: int,
    db: DbSession,
) -> OfertaResponse:
    """Retrieve a single offer by its numeric ID."""
    oferta = await oferta_service.get_oferta(oferta_id, db)
    if oferta is None:
        raise NotFoundException(detail=f"Oferta {oferta_id} not found")
    return oferta


# ---------------------------------------------------------------------------
# Admin endpoints (X-API-Key required)
# ---------------------------------------------------------------------------

@router.post(
    "/cleanup",
    summary="Deactivate stale offers (admin)",
)
async def cleanup_stale(
    db: DbSession,
    _admin: AdminAuth,
    stale_hours: int | None = Query(default=None, description="Override stale threshold (hours)"),
) -> dict:
    """Mark offers as inactive if their scraped_at is older than the configured
    threshold (default: OFFER_STALE_HOURS from settings). Returns per-source counts."""
    result = await oferta_service.cleanup_stale_offers(db, stale_hours)
    if result:
        await db.commit()
    total = sum(result.values()) if result else 0
    return {"deactivated_total": total, "by_source": result}


@router.post(
    "/enrich",
    summary="Trigger barcode enrichment from api_label catalog (admin)",
)
async def trigger_enrich(
    background_tasks: BackgroundTasks,
    _admin: AdminAuth,
) -> dict:
    """Fire barcode enrichment as a background task. Matches offer names against
    api_label product catalog using fuzzy matching and fills in barcode fields."""
    background_tasks.add_task(oferta_service.run_enrich_background)
    return {"status": "enrichment queued"}


@router.post(
    "/scrape/{fuente}",
    response_model=ScrapeResponse,
    summary="Trigger offer scrape (admin)",
)
async def scrape_offers(
    fuente: str,
    db: DbSession,
    _admin: AdminAuth,
    background_tasks: BackgroundTasks,
) -> ScrapeResponse:
    """Scrape price-drop offers from a supported source (mercadona|carrefour).

    Requires X-API-Key header.
    """
    fuente_lower = fuente.lower()

    if fuente_lower == "mercadona":
        offers = await oferta_service.scrape_mercadona()
        source_domain = "tienda.mercadona.es"
    elif fuente_lower == "carrefour":
        offers = await oferta_service.scrape_carrefour()
        source_domain = "www.carrefour.es"
    elif fuente_lower == "masymas":
        offers = await oferta_service.scrape_masymas()
        source_domain = "supermasymasonline.com"
    elif fuente_lower == "aldi":
        offers = await oferta_service.scrape_aldi()
        source_domain = "aldi.es"
    elif fuente_lower == "alcampo":
        offers = await oferta_service.scrape_alcampo()
        source_domain = "www.compraonline.alcampo.es"
    elif fuente_lower == "alimerka":
        offers = await oferta_service.scrape_alimerka()
        source_domain = "alimerkaonline.es"
    elif fuente_lower == "familia" or fuente_lower == "familiaonline":
        offers = await oferta_service.scrape_familia()
        source_domain = "www.familiaonline.es"
    elif fuente_lower == "gadis" or fuente_lower == "gadisline":
        offers = await oferta_service.scrape_gadis()
        source_domain = "www.gadisline.com"
    else:
        from src.core.exceptions import BadRequestException
        raise BadRequestException(detail=f"Fuente '{fuente}' no soportada. Usa: mercadona, carrefour, masymas, aldi, alcampo, alimerka, familia, gadis")

    total_found = len(offers)
    logger.info("Scrape found %d price-drop offers from %s", total_found, source_domain)

    saved, duplicates, deactivated = await oferta_service.save_offers(offers, source_domain, db)
    await db.commit()

    logger.info(
        "Scrape complete for %s: saved=%d, updated=%d, deactivated_previous=%d",
        source_domain, saved, duplicates, deactivated,
    )

    # Fire barcode enrichment after scraping completes (non-blocking)
    background_tasks.add_task(oferta_service.run_enrich_background)
    logger.info("Enrichment task queued after scrape of %s", source_domain)

    return ScrapeResponse(
        total_found=total_found,
        saved=saved,
        duplicates_skipped=duplicates,
        deactivated_previous=deactivated,
        source=source_domain,
    )


@router.delete(
    "/fuente/{fuente}",
    summary="Delete all offers from a source (admin)",
)
async def delete_fuente(
    fuente: str,
    db: DbSession,
    _admin: AdminAuth,
) -> dict:
    """Hard-delete all offers from the given source domain. Requires X-API-Key."""
    count = await oferta_service.delete_fuente(fuente, db)
    return {"deleted": count, "source": fuente}
