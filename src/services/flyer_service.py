"""Flyer (folleto) PDF extraction using GPT vision.

Pipeline: PDF bytes → page images (PyMuPDF) → GPT-5-mini vision → structured products.
"""

import base64
import json
import logging

import fitz  # PyMuPDF
from openai import OpenAI

from src.core.config import settings
from src.schemas.flyer import FlyerProduct

logger = logging.getLogger(__name__)

VALID_SUPERMARKETS = {
    "carrefour", "alimerka", "masymas", "aldi",
    "alcampo", "familia", "gadis",
}

# Rough pricing for GPT-5-mini vision (USD per 1M tokens)
_INPUT_COST_PER_M = 1.25
_OUTPUT_COST_PER_M = 5.00

_PROMPT_TEMPLATE = """Eres un extractor de datos de folletos de supermercado. Analiza esta imagen \
de un folleto de {supermarket} y extrae ABSOLUTAMENTE TODOS los productos visibles, sin excepción.

Los folletos de supermercado contienen muchos productos por página (normalmente entre 4 y 20). \
Examina toda la imagen con cuidado: arriba, abajo, esquinas, laterales, recuadros pequeños. \
NO te saltes ningún producto aunque esté parcialmente visible o en letra pequeña.

Para cada producto, devuelve:
- producto_nombre: nombre completo tal como aparece (marca + descripción + peso/volumen/unidades). \
  Ejemplo: "Aceite de oliva virgen extra CARBONELL 1L", "Yogur natural DANONE pack 4x125g"
- precio_oferta: precio de venta/oferta en euros (float), o null si no aparece
- precio_original: precio anterior/tachado en euros (float), o null si no aparece
- descuento_porcentaje: porcentaje de descuento (float 0-100). Si no aparece explícito pero hay \
  precio_original y precio_oferta, CALCULA el descuento: ((original - oferta) / original) * 100, \
  redondeado a entero. Si no hay datos para calcularlo, null

Responde SOLO con JSON válido: {{"productos": [...]}}
Si no hay productos, responde: {{"productos": []}}
Ignora banners publicitarios, logos y texto decorativo. Extrae solo productos con al menos un precio visible."""


def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD from token counts."""
    return round(
        (input_tokens / 1_000_000) * _INPUT_COST_PER_M
        + (output_tokens / 1_000_000) * _OUTPUT_COST_PER_M,
        6,
    )


def pdf_to_images_base64(pdf_bytes: bytes, dpi: int = 150, max_pages: int | None = None) -> list[str]:
    """Convert PDF pages to base64-encoded PNG strings. Only converts up to max_pages."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    limit = max_pages if max_pages else len(doc)
    for i, page in enumerate(doc):
        if i >= limit:
            break
        pixmap = page.get_pixmap(dpi=dpi)
        png_bytes = pixmap.tobytes("png")
        images.append(base64.b64encode(png_bytes).decode("ascii"))
    doc.close()
    return images


def pdf_to_images_selected(pdf_bytes: bytes, page_indices: list[int], dpi: int = 150) -> list[tuple[int, str]]:
    """Convert only selected PDF pages to (page_number, base64_png) tuples.

    page_indices are 0-based.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for idx in page_indices:
        if idx < len(doc):
            page = doc[idx]
            pixmap = page.get_pixmap(dpi=dpi)
            png_bytes = pixmap.tobytes("png")
            images.append((idx + 1, base64.b64encode(png_bytes).decode("ascii")))
    doc.close()
    return images


def _get_client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def extract_offers_from_image(
    client: OpenAI,
    image_b64: str,
    supermarket: str,
    page_number: int,
) -> tuple[list[FlyerProduct], int, int]:
    """Send a single page image to GPT vision and parse products.

    Returns (products, input_tokens, output_tokens).
    """
    prompt = _PROMPT_TEMPLATE.format(supermarket=supermarket)

    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_b64}",
                },
            ],
        }],
        max_output_tokens=settings.OPENAI_MAX_TOKENS,
    )

    text = response.output_text
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0

    # Parse JSON from response
    products: list[FlyerProduct] = []
    try:
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)
        raw_products = data.get("productos", [])
        for p in raw_products:
            products.append(FlyerProduct(
                producto_nombre=p.get("producto_nombre", "").strip(),
                precio_oferta=p.get("precio_oferta"),
                precio_original=p.get("precio_original"),
                descuento_porcentaje=p.get("descuento_porcentaje"),
            ))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Page %d: failed to parse GPT response: %s", page_number, exc)
        logger.debug("Raw response: %s", text[:500])

    return products, input_tokens, output_tokens


def extract_single_page(
    pdf_bytes: bytes,
    supermarket: str,
    page: int = 1,
) -> tuple[list[FlyerProduct], float, str | None]:
    """Extract products from a single page. Returns (products, cost_usd, raw_text)."""
    images = pdf_to_images_base64(pdf_bytes, dpi=settings.FLYER_DPI)

    if page < 1 or page > len(images):
        raise ValueError(f"Page {page} out of range (PDF has {len(images)} pages)")

    client = _get_client()
    image_b64 = images[page - 1]

    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": _PROMPT_TEMPLATE.format(supermarket=supermarket)},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{image_b64}",
                },
            ],
        }],
        max_output_tokens=settings.OPENAI_MAX_TOKENS,
    )

    raw_text = response.output_text
    in_tokens = response.usage.input_tokens if response.usage else 0
    out_tokens = response.usage.output_tokens if response.usage else 0
    cost = round(
        (in_tokens / 1_000_000) * _INPUT_COST_PER_M
        + (out_tokens / 1_000_000) * _OUTPUT_COST_PER_M,
        6,
    )

    products: list[FlyerProduct] = []
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        data = json.loads(cleaned)
        for p in data.get("productos", []):
            products.append(FlyerProduct(
                producto_nombre=p.get("producto_nombre", "").strip(),
                precio_oferta=p.get("precio_oferta"),
                precio_original=p.get("precio_original"),
                descuento_porcentaje=p.get("descuento_porcentaje"),
            ))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Preview parse error: %s", exc)

    return products, cost, raw_text
