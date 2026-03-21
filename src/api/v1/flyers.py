"""Flyer (folleto) extraction endpoints — admin only."""

import asyncio
import base64
import json
import logging

import fitz
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from src.core.dependencies import AdminAuth, DbSession
from src.schemas.flyer import FlyerPreviewResponse
from src.schemas.oferta import OfertaCreate
from src.services import flyer_service, oferta_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flyers", tags=["flyers"])

# Mapping: supermarket key → web scraper fuente domain
_WEB_FUENTE = {
    "carrefour": "www.carrefour.es",
    "alimerka": "alimerkaonline.es",
    "masymas": "supermasymasonline.com",
    "aldi": "aldi.es",
    "alcampo": "www.compraonline.alcampo.es",
    "familia": "www.familiaonline.es",
    "gadis": "www.gadisline.com",
}


@router.get(
    "/check/{supermarket}",
    summary="Check how many flyer offers exist for a supermarket (admin)",
)
async def check_existing(
    supermarket: str,
    db: DbSession,
    _admin: AdminAuth,
) -> dict:
    """Return count of active offers from folleto:<supermarket>."""
    fuente = f"folleto:{supermarket.lower().strip()}"
    from sqlalchemy import select, func
    from src.models.oferta import Oferta
    result = await db.execute(
        select(func.count()).where(
            Oferta.fuente == fuente,
            Oferta.activo == True,  # noqa: E712
        )
    )
    count = result.scalar_one()
    return {"fuente": fuente, "count": count}


@router.post(
    "/thumbnails",
    summary="Generate low-res page thumbnails from a PDF (admin)",
)
async def get_thumbnails(
    _admin: AdminAuth,
    file: UploadFile = File(...),
) -> dict:
    """Return base64 JPEG thumbnails for each page at low resolution."""
    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    thumbnails = []
    for page in doc:
        pix = page.get_pixmap(dpi=50)
        jpg_bytes = pix.tobytes("jpeg")
        thumbnails.append(base64.b64encode(jpg_bytes).decode("ascii"))
    total = len(doc)
    doc.close()
    return {"pages": total, "thumbnails": thumbnails}


@router.post(
    "/extract",
    summary="Extract products from a supermarket flyer PDF with SSE progress (admin)",
)
async def extract_flyer(
    request: Request,
    db: DbSession,
    _admin: AdminAuth,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    supermarket: str = Form(...),
    pages: str = Form("", description="Pages to extract: '1,3,5-10' or empty for all"),
    save: bool = Form(True),
):
    """Upload PDF → stream SSE events per page → save to DB."""
    supermarket = supermarket.lower().strip()
    if supermarket not in flyer_service.VALID_SUPERMARKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Supermarket '{supermarket}' not valid. Options: {sorted(flyer_service.VALID_SUPERMARKETS)}",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    pdf_bytes = await file.read()
    max_size = flyer_service.settings.FLYER_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(pdf_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(pdf_bytes) / 1024 / 1024:.1f} MB). Max: {flyer_service.settings.FLYER_MAX_FILE_SIZE_MB} MB",
        )

    # Count total pages (quick, no rendering)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages_pdf = len(doc)
    doc.close()

    # Parse page selection (e.g. "1,3,5-10")
    selected_indices = _parse_pages(pages, total_pages_pdf)

    # Only convert selected pages
    try:
        images = flyer_service.pdf_to_images_selected(
            pdf_bytes, selected_indices, dpi=flyer_service.settings.FLYER_DPI
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Error converting PDF: {exc}")

    total_to_process = len(images)
    # images is list of (page_number, base64_str)
    pages_to_process = images
    fuente = f"folleto:{supermarket}"

    CONCURRENCY = 4  # pages processed in parallel

    async def event_stream():
        client = flyer_service._get_client()
        all_products = []
        all_pages = []
        total_in = 0
        total_out = 0
        errors = []
        pages_done = 0

        # Send init event
        yield _sse({"type": "init", "total_pages": total_pages_pdf, "pages_to_process": total_to_process})

        # Process in batches of CONCURRENCY
        for batch_start in range(0, total_to_process, CONCURRENCY):
            batch_items = pages_to_process[batch_start:batch_start + CONCURRENCY]

            # Send "processing" event for the batch
            batch_page_nums = [pn for pn, _ in batch_items]
            yield _sse({
                "type": "processing",
                "page": pages_done + 1,
                "page_end": pages_done + len(batch_items),
                "total": total_to_process,
                "page_nums": batch_page_nums,
            })

            # Launch all pages in this batch concurrently
            async def process_page(page_num, image_b64):
                return page_num, await asyncio.to_thread(
                    flyer_service.extract_offers_from_image,
                    client, image_b64, supermarket, page_num,
                )

            tasks = [process_page(pn, img) for pn, img in batch_items]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    error_msg = f"Page {batch_items[i][0]}: {result}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                else:
                    pnum, (products, in_tokens, out_tokens) = result
                    total_in += in_tokens
                    total_out += out_tokens

                    page_products = [p.model_dump() for p in products]
                    all_products.extend(products)
                    all_pages.append({
                        "page": pnum,
                        "products_found": len(products),
                        "products": page_products,
                    })

                pages_done += 1

            cost_so_far = flyer_service._calc_cost(total_in, total_out)

            # Send batch completion event
            batch_size = len(batch_items)
            yield _sse({
                "type": "page_done",
                "page": pages_done,
                "total": total_to_process,
                "products_found": sum(
                    p["products_found"] for p in all_pages[-batch_size:]
                ) if all_pages else 0,
                "total_products_so_far": len(all_products),
            })

        # Save using the same upsert pattern as web scrapers:
        # deactivate old → upsert → snapshot
        saved = 0
        updated = 0
        deactivated = 0

        if save and all_products:
            from src.db.repositories.oferta_repository import OfertaRepository

            repo = OfertaRepository(db)

            # Deactivate all previous offers for this folleto source
            deactivated = await repo.deactivate_by_fuente(fuente)
            logger.info("Flyer %s: deactivated %d previous offers", fuente, deactivated)

            for p in all_products:
                if not p.producto_nombre:
                    continue
                # Check if the product already exists (from a previous extraction)
                existing = await repo.get_by_name_and_fuente(p.producto_nombre, fuente)
                if existing:
                    existing.precio_oferta = p.precio_oferta
                    existing.precio_original = p.precio_original
                    existing.descuento_porcentaje = p.descuento_porcentaje
                    existing.activo = True
                    from datetime import datetime, timezone
                    existing.scraped_at = datetime.now(timezone.utc)
                    await db.flush()
                    updated += 1
                else:
                    await repo.create(OfertaCreate(
                        producto_nombre=p.producto_nombre,
                        precio_oferta=p.precio_oferta,
                        precio_original=p.precio_original,
                        descuento_porcentaje=p.descuento_porcentaje,
                        fuente=fuente,
                        producto_url=None,
                        imagen_url=None,
                    ))
                    saved += 1

            await db.commit()
            logger.info(
                "Flyer %s: saved=%d new, updated=%d existing, deactivated=%d previous",
                fuente, saved, updated, deactivated,
            )

            # Enrich images from web scraper offers of the same supermarket
            web_fuente = _WEB_FUENTE.get(supermarket)
            if web_fuente:
                try:
                    enriched = await repo.enrich_images_from_web(fuente, web_fuente)
                    if enriched:
                        await db.commit()
                        logger.info("Flyer %s: enriched %d offers with images from %s", fuente, enriched, web_fuente)
                except Exception as exc:
                    logger.warning("Image enrichment failed for %s: %s", fuente, exc)

            # Fallback: enrich remaining imageless offers from OFF
            from src.services.oferta_service import run_image_enrichment_background
            background_tasks.add_task(run_image_enrichment_background)

            # Create snapshot for evolution charts
            try:
                from src.db.repositories.snapshot_repository import SnapshotRepository
                snap_repo = SnapshotRepository(db)
                await snap_repo.create_from_live_data(fuente)
                await db.commit()
                logger.info("Snapshot created for %s", fuente)
            except Exception as exc:
                logger.warning("Snapshot creation failed for %s: %s", fuente, exc)

            asyncio.create_task(oferta_service.run_enrich_background())

        all_pages.sort(key=lambda p: p["page"])

        # Send "done" event
        total_cost = flyer_service._calc_cost(total_in, total_out)
        yield _sse({
            "type": "done",
            "total_pages": total_pages_pdf,
            "pages_processed": len(all_pages),
            "total_products_found": len(all_products),
            "saved": saved,
            "updated": updated,
            "deactivated": deactivated,
            "source": fuente,
            "pages": all_pages,
            "errors": errors,
            "cost_usd": total_cost,
            "tokens_input": total_in,
            "tokens_output": total_out,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/update-duplicates",
    summary="Update existing offers with new data from flyer extraction (admin)",
)
async def update_duplicates(
    db: DbSession,
    _admin: AdminAuth,
    data: dict,
) -> dict:
    """Receive a list of products to update (duplicates the user confirmed)."""
    fuente = data.get("fuente", "")
    products = data.get("products", [])

    if not products or not fuente:
        return {"updated": 0}

    from src.db.repositories.oferta_repository import OfertaRepository
    from datetime import datetime, timezone
    repo = OfertaRepository(db)
    updated = 0

    for p in products:
        name = p.get("producto_nombre", "").strip()
        if not name:
            continue
        existing = await repo.get_by_name_and_fuente(name, fuente)
        if existing:
            existing.precio_oferta = p.get("precio_oferta")
            existing.precio_original = p.get("precio_original")
            existing.descuento_porcentaje = p.get("descuento_porcentaje")
            existing.activo = True
            existing.scraped_at = datetime.now(timezone.utc)
            await db.flush()
            updated += 1

    await db.commit()
    return {"updated": updated}


def _parse_pages(pages_str: str, total: int) -> list[int]:
    """Parse '1,3,5-10' into sorted list of 0-based page indices.

    Empty string means all pages.
    """
    pages_str = pages_str.strip()
    if not pages_str:
        return list(range(total))

    indices = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start.strip()))
            end = min(total, int(end.strip()))
            for i in range(start, end + 1):
                indices.add(i - 1)  # 0-based
        else:
            p = int(part)
            if 1 <= p <= total:
                indices.add(p - 1)
    return sorted(indices)


def _sse(data: dict) -> str:
    """Format a dict as an SSE event."""
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post(
    "/extract/preview",
    response_model=FlyerPreviewResponse,
    summary="Preview extraction from a single page (admin, no save)",
)
async def preview_extraction(
    _admin: AdminAuth,
    file: UploadFile = File(...),
    supermarket: str = Form(...),
    page: int = Form(1, ge=1),
) -> FlyerPreviewResponse:
    """Extract products from a single PDF page without saving."""
    supermarket = supermarket.lower().strip()
    if supermarket not in flyer_service.VALID_SUPERMARKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Supermarket '{supermarket}' not valid. Options: {sorted(flyer_service.VALID_SUPERMARKETS)}",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    pdf_bytes = await file.read()
    max_size = flyer_service.settings.FLYER_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(pdf_bytes) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max: {flyer_service.settings.FLYER_MAX_FILE_SIZE_MB} MB",
        )

    try:
        products, cost, raw_text = await asyncio.to_thread(
            flyer_service.extract_single_page, pdf_bytes, supermarket, page
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return FlyerPreviewResponse(
        page=page,
        products=products,
        estimated_cost_usd=cost,
        raw_response=raw_text,
    )
