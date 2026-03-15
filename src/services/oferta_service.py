"""Service for scraping price-drop offers and persisting them to the DB.

Mercadona API strategy
----------------------
Mercadona's tienda online exposes a public JSON API (no auth required):

  GET https://tienda.mercadona.es/api/categories/?lang=es&wh=<warehouse>
    → list of top-level categories, each with sub-categories (id, name)

  GET https://tienda.mercadona.es/api/categories/<id>/?lang=es&wh=<warehouse>
    → sub-categories with full product list including price_instructions

A product is a "bajada de precio" (price drop) when:
  price_instructions.previous_unit_price is not None

Carrefour scraping strategy
----------------------------
Carrefour Spain exposes a public cloud-api JSON endpoint (no auth required):

  GET https://www.carrefour.es/cloud-api/plp-food-papi/v1{path}?offset=N&rows=100
    → paginated product list for a promotion-filtered category

A product is a genuine "price drop" when:
  item.strikethrough_price is not None

Aldi scraping strategy
-----------------------
Aldi Spain uses Adobe Experience Manager (AEM). The main offers page at
https://www.aldi.es/ofertas.html renders product tiles as lazy-loaded AEM
HTML fragments referenced in the page HTML via data-t-name="TileGroup" blocks.

Each TileGroup has a data-rel attribute identifying the section (e.g.
"2026-03-09-1-frescos-lunes-fruta-verdura") and contains a list of tile
fragment URLs like:
  /content/aldi/spain/es/web-consumer/ofertas/desde-9-marzo/jcr:content/...

Each tile fragment returns a small HTML snippet containing:
  - data-article JSON attribute with productName, priceWithTax, productID, brand
  - <s class="price__previous"> with the original (crossed-out) price
  - srcset attribute for the product image
  - <a href="/ofertas/..."> with the product page URL

Sections are classified upfront — food sections are scraped entirely;
mixed sections (Especial XXL, Especial Francia, Especial India, Fin de semana)
are filtered using a keyword classifier on product names.

Alcampo scraping strategy
--------------------------
Alcampo (compraonline.alcampo.es) is a React/SSR app backed by CloudFront.
The product data API (webproductpagews) is WAF-protected and returns 403
to non-browser clients. However, the SSR page embeds all product data in
window.__INITIAL_STATE__ as a JSON object in the page HTML.

Strategy:
  1. Fetch the main "Folletos y Promociones" page (OCFYP) plus all 9 leaf
     sub-category pages.
  2. Parse window.__INITIAL_STATE__ from each page to extract
     data.products.productEntities — a dict of productId → entity.
  3. Each entity includes: name, price.current.amount, image.src,
     retailerProductId, and an offers[] array.
  4. Retain only entities that have at least one offer with type == "OFFER".
  5. precio_original is not exposed by the SSR layer (requires the
     WAF-protected API), so it is stored as None.
  6. Product URL is constructed as:
       https://www.compraonline.alcampo.es/products/{slug}/{retailerProductId}
     where slug = name lowercased with non-alphanumeric chars replaced by "-".
  7. Deduplicate by productId across all pages (each page loads a different
     first-viewport batch of ~40-50 entities, with some overlap).

Typical yield: ~280-330 unique promotional products per scrape.
"""

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx
from curl_cffi.requests import AsyncSession as CurlSession
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories.oferta_repository import OfertaRepository
from src.schemas.oferta import OfertaCreate, ScrapeResponse

logger = logging.getLogger(__name__)

# Mercadona API constants
_BASE_API = "https://tienda.mercadona.es/api"
_DEFAULT_WH = "3078"
_LANG = "es"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://tienda.mercadona.es/",
}
_REQUEST_TIMEOUT = 30.0
_DELAY_BETWEEN_REQUESTS = 0.5


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _parse_price(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.index(",") > cleaned.index("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _calculate_discount(original: float, offer: float) -> float | None:
    if original and offer and original > 0 and offer < original:
        return round((1 - offer / original) * 100, 1)
    return None


# ---------------------------------------------------------------------------
# Universal non-food filter (applies to all scrapers)
# ---------------------------------------------------------------------------

_UNIVERSAL_NON_FOOD_KEYWORDS: frozenset[str] = frozenset({
    # Higiene personal
    "champú", "champu", "acondicionador", "mascarilla capilar", "sérum capilar",
    "serum capilar", "ampollas tratamiento", "gel de ducha", "gel de baño",
    "gel de bano", "jabón de manos", "jabon de manos", "jabón corporal",
    "desodorante", "antitranspirante",
    "dentífrico", "dentifrico", "pasta dental", "pasta de dientes",
    "enjuague bucal", "colutorio",
    "eau de parfum", "eau de toilette", "agua de colonia", "agua de tocador",
    "colonia infantil",
    "maquinilla de afeitar", "maquinillas de afeitar", "cuchillas de afeitar",
    "aftershave", "espuma de afeitar",
    "crema corporal", "crema de manos", "crema hidratante corporal",
    "loción corporal", "locion corporal",
    "compresas", "tampón", "tampon", "copa menstrual",
    "pañal", "panal", "toallitas húmedas", "toallitas bebe", "toallitas bebé",
    # Droguería / limpieza
    "detergente", "suavizante", "quitamanchas",
    "lejía", "lejia",
    "gel lavavajillas", "pastillas lavavajillas", "limpiamáquinas", "limpiamaquinas",
    "detergente lavavajillas",
    "limpiador multiusos", "limpiador desinfectante", "limpiador baño",
    "limpiador cocina", "limpiador vitro", "limpiador suelos", "limpiador superficies",
    "limpiacristales", "friegasuelos", "fregona",
    "ambientador", "desengrasante", "insecticida", "antiparasitario",
    "bolsas de basura", "bolsas basura",
    "papel higiénico", "papel higienico", "papel wc",
    "papel de cocina", "papel cocina multiusos",
    # Hogar / bazar
    "sartén", "sartenes", "batería de cocina", "cacerola", "olla express",
    "cuchillo pelador", "cuchillo multiusos", "set cuchillos",
    "lavavajillas qilive", "lavavajillas q.",
    # Mascotas
    "pienso para", "arena para gato", "arena gato",
    "snacks para perro", "snacks para gato", "alimento para gato", "alimento para perro",
})


def _is_non_food(name: str) -> bool:
    """Return True if the product name matches any universal non-food keyword."""
    lower = name.lower()
    return any(kw in lower for kw in _UNIVERSAL_NON_FOOD_KEYWORDS)


# ---------------------------------------------------------------------------
# Scraping logic
# ---------------------------------------------------------------------------

async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | list | None:
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("HTTP %s for %s", exc.response.status_code, url)
        return None
    except Exception as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return None


def _extract_offers_from_category_data(data: dict) -> list[OfertaCreate]:
    offers: list[OfertaCreate] = []
    fuente = "tienda.mercadona.es"

    subcategories = data.get("categories", [])
    for subcat in subcategories:
        products = subcat.get("products", [])
        for product in products:
            price_info = product.get("price_instructions", {})
            previous_raw = price_info.get("previous_unit_price")

            if previous_raw is None:
                continue

            precio_original = _parse_price(previous_raw)
            precio_oferta = _parse_price(price_info.get("unit_price"))

            if precio_oferta is None or precio_oferta <= 0:
                continue
            if precio_original is not None and precio_original <= precio_oferta:
                continue

            nombre = product.get("display_name", "").strip()
            if not nombre or len(nombre) < 3 or len(nombre) > 400:
                continue
            if _is_non_food(nombre):
                continue

            packaging = product.get("packaging", "")
            unit_size = price_info.get("unit_size")
            size_format = price_info.get("size_format", "")
            if packaging and unit_size and size_format:
                size_str = (
                    str(int(unit_size))
                    if float(unit_size) == int(unit_size)
                    else str(unit_size)
                )
                nombre_completo = f"{nombre} ({packaging} {size_str} {size_format})"
            else:
                nombre_completo = nombre

            descuento = _calculate_discount(precio_original, precio_oferta)

            offers.append(
                OfertaCreate(
                    producto_nombre=nombre_completo,
                    precio_original=precio_original,
                    precio_oferta=precio_oferta,
                    descuento_porcentaje=descuento,
                    imagen_url=product.get("thumbnail"),
                    producto_url=product.get("share_url"),
                    fuente=fuente,
                    activo=True,
                )
            )

    return offers


async def scrape_mercadona(warehouse: str = _DEFAULT_WH) -> list[OfertaCreate]:
    """Fetch ALL Mercadona categories and return all price-drop offers found."""
    all_offers: list[OfertaCreate] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        top_url = f"{_BASE_API}/categories/?lang={_LANG}&wh={warehouse}"
        top_data = await _fetch_json(client, top_url)
        if not top_data:
            logger.error("Failed to fetch top-level categories from Mercadona API")
            return []

        results = top_data.get("results", [])
        if not results:
            logger.error("No categories found in Mercadona API response")
            return []

        leaf_ids: list[int] = []
        for top_cat in results:
            for sub_cat in top_cat.get("categories", []):
                if sub_cat.get("published", True):
                    leaf_ids.append(sub_cat["id"])

        logger.info("Mercadona: found %d leaf categories to scan", len(leaf_ids))

        for cat_id in leaf_ids:
            cat_url = f"{_BASE_API}/categories/{cat_id}/?lang={_LANG}&wh={warehouse}"
            cat_data = await _fetch_json(client, cat_url)
            if cat_data:
                offers = _extract_offers_from_category_data(cat_data)
                all_offers.extend(offers)
                if offers:
                    logger.debug("Category %s: %d price-drop products", cat_id, len(offers))
            await asyncio.sleep(_DELAY_BETWEEN_REQUESTS)

    logger.info("Mercadona scrape complete: %d price-drop offers", len(all_offers))
    return all_offers


# ---------------------------------------------------------------------------
# Carrefour scraping
# ---------------------------------------------------------------------------

_CARREFOUR_BASE = "https://www.carrefour.es"
_CARREFOUR_FUENTE = "www.carrefour.es"
_CARREFOUR_API_BASE = "https://www.carrefour.es/cloud-api/plp-food-papi/v1"
_CARREFOUR_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.carrefour.es/supermercado/ofertas/cat20968591/c",
    "Origin": "https://www.carrefour.es",
}
# Anonymous session cookies — no login required, just establishes salepoint (Madrid)
_CARREFOUR_COOKIES = {
    "Wizard": "true",
    "salepoint": "005290||28232|A_DOMICILIO|0",
}
_CARREFOUR_PAGE_SIZE = 24  # API returns max 24 per page
_CARREFOUR_DELAY = 0.35

_CARREFOUR_PROMO_PATHS: list[str] = [
    "/supermercado/productos-frescos-promocion/F-10flZ13rjo/c",
    "/supermercado/la-despensa-promocion/F-13ji8Z13rjo/c",
    "/supermercado/bebidas-promocion/F-1086Z13rjo/c",
    "/supermercado/congelados-promocion/F-12r0pZ13rjo/c",
    "/supermercado/perfumeria-e-higiene-promocion/F-107gZ13rjo/c",
    "/supermercado/limpieza-y-hogar-promocion/F-10gcZ13rjo/c",
]


def _parse_carrefour_price(price_str: str) -> float | None:
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d,.]", "", price_str.strip())
    if not cleaned:
        return None
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        if cleaned.index(",") > cleaned.index("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _carrefour_item_to_oferta(item: dict) -> OfertaCreate | None:
    nombre = " ".join((item.get("name") or "").strip().split())
    if not nombre or len(nombre) < 3 or len(nombre) > 500:
        return None
    if _is_non_food(nombre):
        return None

    precio_oferta = _parse_carrefour_price(item.get("price"))
    precio_original = _parse_carrefour_price(item.get("strikethrough_price"))

    if precio_oferta is None or precio_oferta <= 0:
        return None
    if precio_original is None or precio_original <= precio_oferta:
        return None

    descuento = _calculate_discount(precio_original, precio_oferta)

    product_path = item.get("url") or ""
    if product_path and not product_path.startswith("http"):
        product_url: str | None = f"{_CARREFOUR_BASE}{product_path}"
    else:
        product_url = product_path or None

    imagen_url: str | None = (item.get("images") or {}).get("desktop") or None

    return OfertaCreate(
        producto_nombre=nombre,
        precio_original=precio_original,
        precio_oferta=precio_oferta,
        descuento_porcentaje=descuento,
        imagen_url=imagen_url,
        producto_url=product_url,
        fuente=_CARREFOUR_FUENTE,
        activo=True,
    )


async def _scrape_carrefour_category(
    client: CurlSession,
    api_path: str,
    seen_urls: set[str],
) -> list[OfertaCreate]:
    base_url = f"{_CARREFOUR_API_BASE}{api_path}"
    offers: list[OfertaCreate] = []
    offset = 0
    total_results: int | None = None

    while True:
        url = f"{base_url}?offset={offset}&rows={_CARREFOUR_PAGE_SIZE}"
        data = None
        try:
            resp = await client.get(
                url,
                headers=_CARREFOUR_HEADERS,
                cookies=_CARREFOUR_COOKIES,
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code == 404:
                logger.info("Carrefour category not found: %s", api_path)
                return offers
            if resp.status_code != 200:
                logger.warning("Carrefour %s on %s", resp.status_code, url)
                return offers
            data = resp.json()
        except Exception as exc:
            logger.warning("Carrefour request failed for %s: %s", url, exc)
            return offers

        results: dict = data.get("results") or {}
        items: list[dict] = results.get("items") or []
        pagination: dict = results.get("pagination") or {}

        if total_results is None:
            total_results = pagination.get("total_results", 0)
            logger.debug("Carrefour %s: %d total products", api_path, total_results)

        for item in items:
            oferta = _carrefour_item_to_oferta(item)
            if oferta is None:
                continue
            key = oferta.producto_url or oferta.producto_nombre
            if key in seen_urls:
                continue
            seen_urls.add(key)
            offers.append(oferta)

        offset += _CARREFOUR_PAGE_SIZE
        if not items or (total_results is not None and offset >= total_results):
            break

        await asyncio.sleep(_CARREFOUR_DELAY)

    return offers


async def scrape_carrefour() -> list[OfertaCreate]:
    """Scrape Carrefour Spain for genuine price-drop offers via cloud-api JSON.

    Uses curl_cffi with Chrome impersonation to bypass Cloudflare Bot Management
    (TLS/JA3 fingerprint protection). Anonymous salepoint cookie establishes
    region (Madrid 28232) for consistent results.
    """
    all_offers: list[OfertaCreate] = []
    seen_urls: set[str] = set()

    async with CurlSession(impersonate="chrome") as client:
        for api_path in _CARREFOUR_PROMO_PATHS:
            logger.info("Carrefour: scraping promo category %s", api_path)
            offers = await _scrape_carrefour_category(client, api_path, seen_urls)
            all_offers.extend(offers)
            logger.info(
                "Carrefour %s: %d price-drop offers (total so far: %d)",
                api_path.split("/")[2],
                len(offers),
                len(all_offers),
            )
            await asyncio.sleep(_CARREFOUR_DELAY)

    logger.info("Carrefour scrape complete: %d price-drop offers", len(all_offers))
    return all_offers


# ---------------------------------------------------------------------------
# Masymas scraping (Salesforce Commerce Cloud HTML grid endpoint)
# ---------------------------------------------------------------------------

_MASYMAS_BASE = "https://www.supermasymasonline.com"
_MASYMAS_FUENTE = "supermasymasonline.com"
_MASYMAS_GRID_URL = (
    "https://www.supermasymasonline.com/on/demandware.store"
    "/Sites-Masymas-Site/es_ES/Search-UpdateGrid"
    "?cgid=09&start={start}&sz=100"
)
_MASYMAS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.supermasymasonline.com/ofertas/",
}
_MASYMAS_PAGE_SIZE = 100
_MASYMAS_DELAY = 1.0

# Keywords that identify clearly non-food products (cosmetics, hygiene, household).
# Products whose name contains ANY of these (case-insensitive) are skipped.
_MASYMAS_NON_FOOD_KEYWORDS = {
    # Cosmetics / makeup
    "esmalte", "gel nail", "nail repair", "nail colour", "base coat",
    "sombra de ojos", "sombras ojos", "maquillaje", "maquilla.", "foundation",
    "perfilador", "mascara cejas", "mascara para cejas", "colorete", "top coat",
    "pestañas", "barra de labios", "bálsamo labio", "balsamo labio",
    "balsamo mante.labial", "brillo de labios", "brillo labial", "brillo labios",
    "pintalabios", "mousse foundation", "quitacutículas", "quitacuticulas",
    "rimmel", "contorno de ojos", "serum facial", "sérum facial", "crema facial",
    "mascarilla facial", "tratamiento labial", "corrector camouflage",
    "corrector iluminador", "lapiz de ojos", "lápiz de ojos", "colour grip",
    "lapiz de cejas", "lápiz de cejas", "bronceador", "duo sombras",
    "eyeliner", "skin tint", "crema hidratante", "polvos compactos",
    "tratamiento fortale", "tratamiento repara", "brillo volumen",
    "glass shine", "the fake", "prebase", "anti poros",
    # Personal hygiene
    "dentifrico", "dentífrico", "champú", "champu", "desodorante",
    "gel de baño", "gel lima", "gel menta", "enjuague bucal", "mascarilla cabello",
    "cuchilla afeitar", "aftershave", "pasta de dientes", "compresa", "tampón",
    # Household / cleaning / laundry
    "bayeta", "papel higiénico", "papel higienico", "rollo cocina",
    "papel de cocina", "limpiador multiusos", "limpiador para baño",
    "limpiador suelos", "limpiador superficies", "limpiacristales",
    "limpiahogar", "lavavajillas", "suavizante", "lejía", "lejia",
    "bolsas basura", "insecticida", "ambientador", "plancha facil",
    "filtros papel", "pegamento", "baliza de emergencia", "friegasuelos",
    "fregona", "antiparasitario", "detergente", "deter liq",
    "perlas fresh", "lenor", "quitamanchas", "guantes spontex",
    # Pets
    "alimento gato", "alimento para gato", "alimento húmedo gato",
    "pienso perro", "snack liquido gatos", "hueso perro", "mascotas",
    # Non-food appliances / misc
    "cafetera",
}


def _masymas_is_non_food(name: str) -> bool:
    """Return True if the product name matches any non-food keyword."""
    lower = name.lower()
    return any(kw in lower for kw in _MASYMAS_NON_FOOD_KEYWORDS)


def _parse_masymas_page(html: str) -> list[OfertaCreate]:
    """Extract price-drop offers from one SFCC Search-UpdateGrid HTML page."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed — cannot parse Masymas HTML")
        return []

    soup = BeautifulSoup(html, "html.parser")
    products = soup.find_all("div", class_="product", attrs={"data-pid": True})
    offers: list[OfertaCreate] = []

    for p in products:
        # Offer price: first element with [content] inside .sales span
        sales_el = p.find(
            attrs={"class": lambda c: c and "sales" in c.split() if c else False}
        )
        offer_price: float | None = None
        if sales_el:
            val_el = sales_el.find(attrs={"content": True})
            if val_el:
                offer_price = _parse_price(val_el.get("content"))

        # Original price: element with [content] inside .strike-through
        strike_el = p.find(class_="strike-through")
        orig_price: float | None = None
        if strike_el:
            val_el = strike_el.find(attrs={"content": True})
            if val_el:
                orig_price = _parse_price(val_el.get("content"))

        # Only include genuine price drops
        if offer_price is None or offer_price <= 0:
            continue
        if orig_price is None or orig_price <= offer_price:
            continue

        # Product name from tile image alt text
        img_el = p.find("img", class_="tile-image")
        nombre = img_el.get("alt", "").strip() if img_el else ""
        nombre = " ".join(nombre.split())  # collapse whitespace
        if not nombre or len(nombre) < 3 or len(nombre) > 500:
            continue
        if _masymas_is_non_food(nombre):
            continue

        # Product URL (relative → absolute)
        link_container = p.find("div", class_="image-container")
        href = ""
        if link_container:
            a_el = link_container.find("a", href=True)
            if a_el:
                href = a_el["href"]
        if href and not href.startswith("http"):
            href = f"{_MASYMAS_BASE}{href}"
        producto_url: str | None = href or None

        # Image URL (full URL already in src)
        imagen_url: str | None = img_el.get("src") if img_el else None

        descuento = _calculate_discount(orig_price, offer_price)

        offers.append(
            OfertaCreate(
                producto_nombre=nombre,
                precio_original=orig_price,
                precio_oferta=offer_price,
                descuento_porcentaje=descuento,
                imagen_url=imagen_url,
                producto_url=producto_url,
                fuente=_MASYMAS_FUENTE,
                activo=True,
            )
        )

    return offers


async def scrape_masymas() -> list[OfertaCreate]:
    """Scrape Masymas supermercados for genuine price-drop offers.

    Uses the Salesforce Commerce Cloud Search-UpdateGrid HTML endpoint with
    cgid=09 (Ofertas category).  Paginates with start/sz=100 until an empty
    page is returned or 10 pages maximum.
    """
    all_offers: list[OfertaCreate] = []
    seen_urls: set[str] = set()
    start = 0
    max_pages = 10

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for _ in range(max_pages):
            url = _MASYMAS_GRID_URL.format(start=start)
            logger.debug("Masymas: fetching start=%d", start)
            try:
                resp = await client.get(url, headers=_MASYMAS_HEADERS, timeout=_REQUEST_TIMEOUT)
                resp.raise_for_status()
                html = resp.text
            except httpx.HTTPStatusError as exc:
                logger.warning("Masymas HTTP %s at start=%d", exc.response.status_code, start)
                break
            except Exception as exc:
                logger.warning("Masymas request failed at start=%d: %s", start, exc)
                break

            # Empty page means we've gone past the last product
            if len(html.strip()) < 500:
                logger.debug("Masymas: empty page at start=%d, stopping", start)
                break

            page_offers = _parse_masymas_page(html)
            if not page_offers and start > 0:
                # No parseable products → we may have overshot
                logger.debug("Masymas: no offers at start=%d, stopping", start)
                break

            new_count = 0
            for offer in page_offers:
                key = offer.producto_url or offer.producto_nombre
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                all_offers.append(offer)
                new_count += 1

            logger.info(
                "Masymas start=%d: %d price-drop offers parsed, %d new (total: %d)",
                start,
                len(page_offers),
                new_count,
                len(all_offers),
            )

            start += _MASYMAS_PAGE_SIZE
            await asyncio.sleep(_MASYMAS_DELAY)

    logger.info("Masymas scrape complete: %d price-drop offers", len(all_offers))
    return all_offers


# ---------------------------------------------------------------------------
# Alimerka scraping (Salesforce Commerce Cloud — same HTML grid as Masymas)
# ---------------------------------------------------------------------------

_ALIMERKA_BASE = "https://www.alimerkaonline.es"
_ALIMERKA_FUENTE = "alimerkaonline.es"
_ALIMERKA_ZIPCODE_URL = (
    "https://www.alimerkaonline.es/on/demandware.store"
    "/Sites-Alimerka-Site/default/Stores-FindByZipcode"
)
_ALIMERKA_GRID_URL = (
    "https://www.alimerkaonline.es/on/demandware.store"
    "/Sites-Alimerka-Site/default/Search-UpdateGrid"
    "?cgid=alimerka-null&start={start}&sz=100&format=page-element"
)
_ALIMERKA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.alimerkaonline.es/ofertas",
}
_ALIMERKA_PAGE_SIZE = 100
_ALIMERKA_DELAY = 0.5


def _parse_alimerka_page(html: str) -> list[OfertaCreate]:
    """Extract price-drop offers from Alimerka SFCC Search-UpdateGrid HTML.

    Same DOM structure as Masymas: .product[data-pid], .strike-through .value[content],
    .sales .value[content], .tile-image, .pdp-link a[href].
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed — cannot parse Alimerka HTML")
        return []

    soup = BeautifulSoup(html, "html.parser")
    products = soup.find_all("div", class_="product", attrs={"data-pid": True})
    offers: list[OfertaCreate] = []

    for p in products:
        sales_el = p.find(attrs={"class": lambda c: c and "sales" in c.split() if c else False})
        offer_price: float | None = None
        if sales_el:
            val_el = sales_el.find(attrs={"content": True})
            if val_el:
                offer_price = _parse_price(val_el.get("content"))

        strike_el = p.find(class_="strike-through")
        orig_price: float | None = None
        if strike_el:
            val_el = strike_el.find(attrs={"content": True})
            if val_el:
                orig_price = _parse_price(val_el.get("content"))

        if offer_price is None or offer_price <= 0:
            continue
        if orig_price is None or orig_price <= offer_price:
            continue

        img_el = p.find("img", class_="tile-image")
        nombre = img_el.get("alt", "").strip() if img_el else ""
        nombre = " ".join(nombre.split())
        if not nombre or len(nombre) < 3 or len(nombre) > 500:
            continue
        if _is_non_food(nombre):
            continue

        # Product URL from pdp-link anchor
        pdp_el = p.find("div", class_="pdp-link")
        href = ""
        if pdp_el:
            a_el = pdp_el.find("a", href=True)
            if a_el:
                href = a_el["href"]
        if href and not href.startswith("http"):
            href = f"{_ALIMERKA_BASE}{href}"
        producto_url: str | None = href or None

        imagen_url: str | None = img_el.get("src") if img_el else None

        offers.append(
            OfertaCreate(
                producto_nombre=nombre,
                precio_original=orig_price,
                precio_oferta=offer_price,
                descuento_porcentaje=_calculate_discount(orig_price, offer_price),
                imagen_url=imagen_url,
                producto_url=producto_url,
                fuente=_ALIMERKA_FUENTE,
                activo=True,
            )
        )

    return offers


async def scrape_alimerka() -> list[OfertaCreate]:
    """Scrape Alimerka for genuine price-drop offers via SFCC Search-UpdateGrid.

    Alimerka requires a delivery zone before showing products. Strategy:
      1. GET homepage to obtain SFCC session cookies (dwanonymous, dwac, sid).
      2. GET Stores-FindByZipcode?zipCode=33001 to activate Asturias delivery zone.
      3. Paginate Search-UpdateGrid with cgid=alimerka-null until empty page.
    """
    all_offers: list[OfertaCreate] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Step 1: establish session
        try:
            await client.get(f"{_ALIMERKA_BASE}/", headers=_ALIMERKA_HEADERS, timeout=_REQUEST_TIMEOUT)
        except Exception as exc:
            logger.warning("Alimerka: homepage request failed: %s", exc)
            return []

        # Step 2: set delivery zone (Oviedo 33001)
        try:
            await client.get(
                _ALIMERKA_ZIPCODE_URL,
                params={"consent": "true", "zipCode": "33001"},
                headers={**_ALIMERKA_HEADERS, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
                timeout=_REQUEST_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("Alimerka: zipcode setup failed: %s", exc)
            return []

        # Step 3: paginate offers
        start = 0
        max_pages = 15
        for _ in range(max_pages):
            url = _ALIMERKA_GRID_URL.format(start=start)
            logger.debug("Alimerka: fetching start=%d", start)
            try:
                resp = await client.get(url, headers=_ALIMERKA_HEADERS, timeout=_REQUEST_TIMEOUT)
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                logger.warning("Alimerka: request failed at start=%d: %s", start, exc)
                break

            if len(html.strip()) < 500:
                break

            page_offers = _parse_alimerka_page(html)
            if not page_offers and start > 0:
                break

            new_count = 0
            for offer in page_offers:
                key = offer.producto_url or offer.producto_nombre
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                all_offers.append(offer)
                new_count += 1

            logger.info(
                "Alimerka start=%d: %d price-drop offers parsed, %d new (total: %d)",
                start, len(page_offers), new_count, len(all_offers),
            )

            start += _ALIMERKA_PAGE_SIZE
            await asyncio.sleep(_ALIMERKA_DELAY)

    logger.info("Alimerka scrape complete: %d price-drop offers", len(all_offers))
    return all_offers


# ---------------------------------------------------------------------------
# Aldi scraping (AEM tile-fragment HTML strategy)
# ---------------------------------------------------------------------------

_ALDI_BASE = "https://www.aldi.es"
_ALDI_FUENTE = "aldi.es"
_ALDI_OFFERS_URL = "https://www.aldi.es/ofertas.html"
_ALDI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.aldi.es/",
}
_ALDI_TILE_DELAY = 0.3  # seconds between tile requests
_ALDI_MAX_TILES = 500   # safety cap

# Section IDs that are purely non-food — all tiles in these sections are skipped
_ALDI_NON_FOOD_SECTIONS = {
    "menaje",
    "jardin",
    "jardín",
    "bricolaje",
    "plantas",
    "textil",
    "bicicleta",
    "ciclismo",
    "hogar",
    "viajes",
    "viaje",
    "juguetes",
    "ropa",
    "calzado",
    "textil-adultos",
}

# Section ID keywords that indicate the section is entirely food
_ALDI_FOOD_SECTION_KEYWORDS = {
    "fruta",
    "verdura",
    "carne",
    "pescado",
    "pan",
    "bolleria",
    "bollería",
    "despensa",
    "refrigerados",
    "frescos",
    "alimentacion",
    "alimentación",
}

# Keywords for food classification of individual products in mixed sections
_FOOD_KEYWORDS = {
    # Frutas y verduras
    "fruta", "verdura", "manzana", "pera", "naranja", "limón", "limon",
    "uva", "plátano", "platano", "fresa", "melón", "melon", "sandía",
    "sandia", "piña", "pina", "mango", "kiwi", "aguacate", "tomate",
    "lechuga", "zanahoria", "cebolla", "ajo", "patata", "papa", "pepino",
    "pimiento", "brócoli", "brocoli", "espinaca", "coliflor", "calabacín",
    "calabacin", "berenjena", "espárrago", "esparrago", "alcachofa",
    "judía", "guisante", "apio", "puerro", "rábano",
    # Carnes
    "carne", "pollo", "cerdo", "ternera", "vacuno", "cordero", "pavo",
    "jamón", "jamon", "chorizo", "salchich", "mortadela", "fuet",
    "lomo", "costill", "filete", "chuleta", "hamburguesa", "albóndiga",
    "albondiga", "bacon", "panceta", "morcilla", "embutido", "butifarra",
    "pechuga", "muslo", "ala", "conejo",
    # Pescados y mariscos
    "pescado", "atún", "atun", "salmón", "salmon", "merluza", "bacalao",
    "sardina", "caballa", "dorada", "lubina", "trucha", "langostino",
    "gamba", "mejillón", "mejillon", "calamar", "pulpo", "berberecho",
    "navaja", "sepia", "pez", "boquerón", "boqueron", "anchoa",
    # Lácteos
    "leche", "yogur", "queso", "mantequilla", "nata", "crema",
    "batido", "kéfir", "kefir", "requesón", "requesón", "cuajada",
    "margarina",
    # Panadería y bollería
    "pan", "bollería", "bolleria", "croissant", "brioche", "magdalena",
    "bizcocho", "muffin", "donut", "tostada", "baguette", "hogazas",
    "hogaza", "rebanada", "galleta", "cracker", "barrita",
    # Bebidas
    "agua", "zumo", "jugo", "cerveza", "vino", "cava", "sidra",
    "refresco", "cola", "naranjada", "limonada", "té", "te",
    "café", "cafe", "infusión", "infusion", "bebida", "batido",
    "horchata", "leche vegetal", "soja",
    # Conservas y enlatados
    "conserva", "lata", "tarro", "bote", "enlatado", "escabeche",
    "bonito", "mejillones en", "sardinas en", "caballa en",
    # Pasta, arroz y cereales
    "pasta", "arroz", "cereal", "macarrón", "macarron", "espagueti",
    "espaguetis", "fideos", "quinoa", "cuscús", "cuscus", "avena",
    "muesli", "granola", "copos",
    # Aceites, salsas y condimentos
    "aceite", "vinagre", "salsa", "ketchup", "mayonesa", "mostaza",
    "tomate frito", "sofrito", "caldo", "sopa", "crema de", "puré",
    "pure", "condimento", "especia", "sal ", "pimienta", "pimentón",
    "pimenton", "comino", "curry", "orégano", "oregano",
    "tomillo", "romero",
    # Dulces y snacks
    "chocolate", "cacao", "bombón", "bombon", "caramelo", "gominola",
    "chicle", "snack", "chip", "patatas fritas", "nachos", "palomita",
    "fruto seco", "nuez", "almendra", "cacahuete", "pistacho",
    "anacardo", "pipas", "miel", "mermelada", "confitura",
    "crema de cacahuete", "mantequilla de cacahuete",
    # Congelados
    "congelado", "helado", "ice cream", "pizza congelada",
    "croqueta", "empanada",
    # Platos preparados
    "plato preparado", "lasaña", "lasana", "canelón", "canelon",
    "paella", "cocido", "fabada", "gazpacho", "salmorejo",
    # Otros alimentos
    "huevo", "aceitunas", "pepinillo", "legumbre", "lenteja",
    "garbanzo", "alubia", "judía blanca", "harina", "levadura",
    "azúcar", "azucar", "edulcorante", "stevia", "flan",
    "natillas", "mousse", "pudín", "pudin", "gelatina",
    # Especias / origen específico que sugiere comida
    "basmati", "thai", "sushi", "hummus", "tahini", "falafel",
    "tzatziki", "tapenada", "naan", "chapati", "curry",
    "tikka", "masala", "samosa", "chutney",
    # Especial Francia / India — términos específicos de alimentos
    "brie", "camembert", "roquefort", "gruyère", "gruyere", "emmental",
    "foie", "pâté", "pate", "rillette", "baguette", "éclair", "eclair",
    "tarte", "quiche", "crepe", "crêpe", "macarón", "macaron",
    "dal", "dahl", "basmati", "naan", "papadum", "mango chutney",
    "ghee", "paneer",
}


def _is_food_section(section_id: str) -> bool | None:
    """Return True if section is food, False if non-food, None if mixed/unknown."""
    sid = section_id.lower()
    for kw in _ALDI_NON_FOOD_SECTIONS:
        if kw in sid:
            return False
    for kw in _ALDI_FOOD_SECTION_KEYWORDS:
        if kw in sid:
            return True
    return None  # mixed / unknown — apply keyword filter per product


def _is_food_product(name: str) -> bool:
    """Return True if the product name contains food keywords."""
    name_lower = name.lower()
    for kw in _FOOD_KEYWORDS:
        if kw in name_lower:
            return True
    return False


def _parse_aldi_tile(html: str) -> OfertaCreate | None:
    """Parse a single Aldi AEM tile HTML fragment and return an OfertaCreate or None."""
    try:
        import html as html_module
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed — cannot parse Aldi HTML")
        return None

    soup = BeautifulSoup(html, "html.parser")

    # --- data-article JSON ---
    tile = soup.find(attrs={"data-article": True})
    if not tile:
        return None

    try:
        article_data = json.loads(html_module.unescape(tile["data-article"]))
    except (ValueError, KeyError):
        return None

    product_info = article_data.get("productInfo", {})
    nombre_raw = (product_info.get("productName") or "").strip()
    brand = (product_info.get("brand") or "").strip()
    precio_oferta_raw = product_info.get("priceWithTax")

    if not nombre_raw or len(nombre_raw) < 3 or len(nombre_raw) > 500:
        return None

    # Build full name with brand if present
    if brand:
        nombre = f"{nombre_raw} {brand}"
    else:
        nombre = nombre_raw

    precio_oferta = _parse_price(precio_oferta_raw)
    if precio_oferta is None or precio_oferta <= 0:
        return None

    # --- Original (crossed-out) price ---
    prev_el = soup.find("s", class_=re.compile(r"price__previous"))
    precio_original: float | None = None
    if prev_el:
        precio_original = _parse_price(prev_el.get_text())

    # Reject if original price is not higher than offer price
    if precio_original is not None and precio_original <= precio_oferta:
        precio_original = None

    descuento = _calculate_discount(precio_original, precio_oferta)

    # --- Image URL ---
    # Aldi uses data-srcset (lazy loading), not srcset
    img_el = soup.find("img", attrs={"data-srcset": True})
    imagen_url: str | None = None
    if img_el:
        srcset_val = img_el.get("data-srcset", "")
        # Take first URL from srcset (smallest, e.g. 288w)
        first_src = srcset_val.split(",")[0].strip().split(" ")[0].strip()
        if first_src:
            if first_src.startswith("/"):
                imagen_url = f"{_ALDI_BASE}{first_src}"
            elif first_src.startswith("http"):
                imagen_url = first_src

    # --- Product URL ---
    link_el = soup.find("a", href=re.compile(r"^/ofertas/"))
    producto_url: str | None = None
    if link_el:
        href = link_el.get("href", "")
        if href:
            producto_url = f"{_ALDI_BASE}{href}"

    return OfertaCreate(
        producto_nombre=nombre,
        precio_original=precio_original,
        precio_oferta=precio_oferta,
        descuento_porcentaje=descuento,
        imagen_url=imagen_url,
        producto_url=producto_url,
        fuente=_ALDI_FUENTE,
        activo=True,
    )


def _extract_aldi_sections(html: str) -> dict[str, list[str]]:
    """Parse the main ofertas.html and return {section_id: [tile_fragment_paths]}."""
    sections: dict[str, list[str]] = {}

    # Split on TileGroup boundaries
    blocks = re.split(r"(?=data-t-name=\"TileGroup\")", html)

    for block in blocks[1:]:
        rel_match = re.search(r'data-rel="([^"]+)"', block)
        if not rel_match:
            continue
        section_id = rel_match.group(1)

        # Skip date-only parent groupings (e.g. "2026-03-09")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", section_id):
            continue

        tiles = re.findall(
            r"(/content/aldi/spain/es/web-consumer/ofertas/[^\s\"'<>]+\.html)",
            block,
        )
        if tiles:
            sections[section_id] = tiles

    return sections


async def scrape_aldi() -> list[OfertaCreate]:
    """Scrape Aldi Spain for food offers using the AEM tile-fragment strategy.

    1. Fetch ofertas.html to extract section → tile-fragment URL mapping.
    2. For food-only sections, scrape all tiles.
    3. For mixed/unknown sections, scrape all tiles but filter by food keywords.
    4. Non-food sections are skipped entirely.
    """
    try:
        from bs4 import BeautifulSoup  # noqa: F401 — validate import early
    except ImportError:
        logger.error("beautifulsoup4 not installed — run: pip install beautifulsoup4 lxml")
        return []

    import json as _json  # alias to avoid shadowing module-level import

    all_offers: list[OfertaCreate] = []
    seen_keys: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # --- Step 1: Fetch main offers page ---
        logger.info("Aldi: fetching main offers page %s", _ALDI_OFFERS_URL)
        try:
            resp = await client.get(
                _ALDI_OFFERS_URL, headers=_ALDI_HEADERS, timeout=_REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            main_html = resp.text
        except Exception as exc:
            logger.error("Aldi: failed to fetch main page: %s", exc)
            return []

        sections = _extract_aldi_sections(main_html)
        logger.info(
            "Aldi: found %d sections, %d total tile fragments",
            len(sections),
            sum(len(v) for v in sections.values()),
        )

        # --- Step 2: Scrape tiles by section ---
        total_tiles = 0
        for section_id, tile_paths in sections.items():
            food_flag = _is_food_section(section_id)

            if food_flag is False:
                logger.debug("Aldi: skipping non-food section %s", section_id)
                continue

            logger.info(
                "Aldi: scraping section %s (%d tiles, food=%s)",
                section_id,
                len(tile_paths),
                food_flag,
            )

            for tile_path in tile_paths:
                if total_tiles >= _ALDI_MAX_TILES:
                    logger.warning("Aldi: reached tile cap %d, stopping", _ALDI_MAX_TILES)
                    break

                tile_url = f"{_ALDI_BASE}{tile_path}"
                try:
                    tile_resp = await client.get(
                        tile_url, headers=_ALDI_HEADERS, timeout=_REQUEST_TIMEOUT
                    )
                    if tile_resp.status_code == 404:
                        logger.debug("Aldi: tile 404 %s", tile_path)
                        await asyncio.sleep(_ALDI_TILE_DELAY)
                        continue
                    tile_resp.raise_for_status()
                    tile_html = tile_resp.text
                except Exception as exc:
                    logger.warning("Aldi: tile request failed %s: %s", tile_path, exc)
                    await asyncio.sleep(_ALDI_TILE_DELAY)
                    continue

                total_tiles += 1
                oferta = _parse_aldi_tile(tile_html)
                if oferta is None:
                    await asyncio.sleep(_ALDI_TILE_DELAY)
                    continue

                # Always skip explicit non-food products
                if _is_non_food(oferta.producto_nombre):
                    await asyncio.sleep(_ALDI_TILE_DELAY)
                    continue
                # For mixed sections, also require positive food keywords
                if food_flag is None and not _is_food_product(oferta.producto_nombre):
                    logger.debug(
                        "Aldi: skipping non-food product in mixed section: %s",
                        oferta.producto_nombre,
                    )
                    await asyncio.sleep(_ALDI_TILE_DELAY)
                    continue

                key = oferta.producto_url or oferta.producto_nombre
                if key in seen_keys:
                    await asyncio.sleep(_ALDI_TILE_DELAY)
                    continue
                seen_keys.add(key)
                all_offers.append(oferta)

                await asyncio.sleep(_ALDI_TILE_DELAY)

    logger.info(
        "Aldi scrape complete: %d food offers from %d tiles fetched",
        len(all_offers),
        total_tiles,
    )
    return all_offers


# ---------------------------------------------------------------------------
# Alcampo scraping
# ---------------------------------------------------------------------------

_ALCAMPO_BASE = "https://www.compraonline.alcampo.es"
_ALCAMPO_FUENTE = "www.compraonline.alcampo.es"
_ALCAMPO_REGION_ID = "ac90d761-9d58-4918-a37d-dd14e1ce384a"
_ALCAMPO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}
_ALCAMPO_DELAY = 0.5

# All sub-category pages under "Folletos y Promociones" (OCFYP).
# Each is scraped independently; the first ~40-50 product entities embedded
# in __INITIAL_STATE__ are collected and deduplicated by productId.
_ALCAMPO_CATEGORY_PATHS: list[str] = [
    "/categories/folletos-y-promociones/OCFYP",
    "/categories/folletos-y-promociones/Chocolates-y-dulces-de-Pascua/OCPASCUA",
    "/categories/folletos-y-promociones/Folleto-de-Alimentaci%C3%B3n-excepto-Canarias/OC3009192",
    "/categories/folletos-y-promociones/Folleto-Hogar-y-Tecnolog%C3%ADa/OC3009191",
    "/categories/folletos-y-promociones/Campo-y-Alma-Castilla-La-Mancha/OCCLM",
    "/categories/folletos-y-promociones/Promociones-Club-Alcampo/OCofertasClubAlcampo",
    "/categories/folletos-y-promociones/s%C3%BAper-ofertas-frescos/OC02092021",
    "/categories/folletos-y-promociones/JARD%C3%8DN-y-AIRE-LIBRE/OCJYAL",
    "/categories/folletos-y-promociones/Renueva-la-decoraci%C3%B3n-de-tu-hogar/OCSH",
    "/categories/folletos-y-promociones/Regalos-del-D%C3%ADa-del-Padre/OCFERPA",
]


def _alcampo_extract_initial_state(html: str) -> dict | None:
    """Extract and parse window.__INITIAL_STATE__ from an Alcampo page."""
    marker = "window.__INITIAL_STATE__="
    idx = html.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    depth = 0
    i = start
    while i < len(html):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    else:
        return None
    try:
        return json.loads(html[start:end])
    except (ValueError, KeyError):
        return None


def _alcampo_build_product_url(name: str, retailer_product_id: str) -> str | None:
    """Construct the product page URL from product name and retailer ID."""
    if not name or not retailer_product_id:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return f"{_ALCAMPO_BASE}/products/{slug}/{retailer_product_id}"


def _alcampo_entity_to_oferta(entity: dict) -> OfertaCreate | None:
    """Convert a productEntities entry from __INITIAL_STATE__ to OfertaCreate."""
    nombre = " ".join((entity.get("name") or "").strip().split())
    if not nombre or len(nombre) < 3 or len(nombre) > 500:
        return None

    # Only include products that carry at least one OFFER tag
    offers_list = entity.get("offers") or []
    has_offer = any(o.get("type") == "OFFER" for o in offers_list)
    if not has_offer:
        return None

    price_info = entity.get("price") or {}
    current_price = price_info.get("current") or {}
    precio_oferta = _parse_price(current_price.get("amount"))
    if precio_oferta is None or precio_oferta <= 0:
        return None

    retailer_pid = entity.get("retailerProductId") or ""
    imagen_url: str | None = (entity.get("image") or {}).get("src") or None
    producto_url = _alcampo_build_product_url(nombre, retailer_pid)

    return OfertaCreate(
        producto_nombre=nombre,
        precio_original=None,      # not exposed by SSR layer
        precio_oferta=precio_oferta,
        descuento_porcentaje=None,  # cannot calculate without original price
        imagen_url=imagen_url,
        producto_url=producto_url,
        fuente=_ALCAMPO_FUENTE,
        activo=True,
    )


async def scrape_alcampo() -> list[OfertaCreate]:
    """Scrape Alcampo promotional products from the Folletos y Promociones section.

    Fetches all sub-category pages under OCFYP and extracts product entities
    from window.__INITIAL_STATE__. Each page embeds the first ~40-50 visible
    products. By combining all sub-categories we typically collect 280-330
    unique promotional products.

    Note: precio_original is not available via the SSR layer (the full-price
    API is CloudFront WAF-protected). Offers are identified by the presence of
    an offers[] entry with type == 'OFFER' in the entity data.
    """
    all_entities: dict[str, dict] = {}  # productId → entity

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=_REQUEST_TIMEOUT
    ) as client:
        for path in _ALCAMPO_CATEGORY_PATHS:
            url = f"{_ALCAMPO_BASE}{path}"
            try:
                resp = await client.get(url, headers=_ALCAMPO_HEADERS)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("Alcampo: failed to fetch %s: %s", path, exc)
                await asyncio.sleep(_ALCAMPO_DELAY)
                continue

            state = _alcampo_extract_initial_state(resp.text)
            if state is None:
                logger.warning("Alcampo: no __INITIAL_STATE__ on %s", path)
                await asyncio.sleep(_ALCAMPO_DELAY)
                continue

            entities: dict = (
                state.get("data", {})
                .get("products", {})
                .get("productEntities", {})
            )
            new_count = sum(1 for pid in entities if pid not in all_entities)
            all_entities.update(entities)
            logger.debug(
                "Alcampo: %s → +%d new entities (total: %d)",
                path, new_count, len(all_entities),
            )
            await asyncio.sleep(_ALCAMPO_DELAY)

    logger.info("Alcampo: collected %d unique product entities", len(all_entities))

    all_offers: list[OfertaCreate] = []
    seen_urls: set[str] = set()

    for entity in all_entities.values():
        oferta = _alcampo_entity_to_oferta(entity)
        if oferta is None:
            continue
        if _is_non_food(oferta.producto_nombre):
            continue
        key = oferta.producto_url or oferta.producto_nombre
        if key in seen_urls:
            continue
        seen_urls.add(key)
        all_offers.append(oferta)

    logger.info(
        "Alcampo scrape complete: %d promotional offers from %d entities",
        len(all_offers), len(all_entities),
    )
    return all_offers


# ---------------------------------------------------------------------------
# Familia Online scraping (Eroski / Apache Tapestry platform)
# ---------------------------------------------------------------------------
#
# Familia Online (www.familiaonline.es) is an online supermarket powered by
# Apache Tapestry 5.6.2 on the Eroski group platform.
#
# The /filter/offers/ page requires authentication, but individual category
# pages are publicly accessible as Googlebot (allowed by robots.txt). Products
# are rendered as full HTML in each category page (server-side rendering).
#
# Strategy:
#   1. Fetch the sitemap.xml to get all category URLs.
#   2. Filter to standard numeric category paths (IDs starting with digits),
#      ignoring brand/manufacturer pages (paths starting with letters) and
#      capping at _FAMILIA_MAX_CATEGORIES.
#   3. For each category page, extract div.product-item containers.
#   4. A product is a genuine price drop when span.price-before contains
#      child span.price-offer-before with a non-empty text value.
#   5. Product data is extracted from:
#      - data-metrics JSON (item_name, item_id, price) — most reliable
#      - span.price-offer-now — current offer price
#      - span.price-offer-before — original price
#      - a.product-image[href] — product detail URL
#      - img.product-img[src] — product image URL
#   6. Deduplicate by item_id across all category pages.
#
# Typical yield: 200-500 food price-drop offers per scrape.

_FAMILIA_BASE = "https://www.familiaonline.es"
_FAMILIA_FUENTE = "www.familiaonline.es"
_FAMILIA_SITEMAP_URL = "https://www.familiaonline.es/sitemap.xml"
_FAMILIA_HEADERS = {
    "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}
_FAMILIA_DELAY = 0.4         # seconds between category requests
_FAMILIA_MAX_CATEGORIES = 800  # cap to keep scrape time reasonable (~5-6 min)


def _familia_is_standard_category(path_segment: str) -> bool:
    """Return True if the category path segment is a numeric Eroski category ID.

    Standard categories look like '2059698-frescos', '2059710-verduras-y-hortalizas'.
    Brand/manufacturer pages look like 'borges/', 'syoss/', 'knoor/' — pure alpha.
    """
    # The first segment after /supermercado/ must start with a digit
    first_seg = path_segment.lstrip("/").split("/")[0]
    return bool(first_seg) and (first_seg[0].isdigit() or first_seg[0] in "0123456789")


def _familia_extract_products(html: str) -> list[OfertaCreate]:
    """Parse one Familia Online category page and return price-drop offers."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 not installed — cannot parse Familia Online HTML")
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers: list[OfertaCreate] = []

    # Each product container is div.product-item (with class big-item on category pages)
    # We walk via the price-before spans to guarantee we only grab products with offers
    pb_spans = soup.find_all("span", class_="price-before")
    seen_ids: set[str] = set()

    for pb in pb_spans:
        # Only process if this price-before has a non-empty original price
        before_val_el = pb.find("span", class_="price-offer-before")
        if not before_val_el:
            continue
        before_text = before_val_el.get_text(strip=True)
        if not before_text:
            continue

        precio_original = _parse_price(before_text)
        if precio_original is None or precio_original <= 0:
            continue

        # Walk up to find the product-item container (up to 8 levels)
        container = pb
        product_el = None
        for _ in range(8):
            container = container.parent
            if not container:
                break
            cls = " ".join(container.get("class", []))
            if "product-item" in cls:
                product_el = container
                break

        if product_el is None:
            continue

        # --- Product ID and name from data-metrics JSON ---
        metrics_el = product_el.find(attrs={"data-metrics": True})
        item_id: str | None = None
        nombre: str = ""
        if metrics_el:
            try:
                mdata = json.loads(metrics_el.get("data-metrics", "{}"))
                items_list = mdata.get("ecommerce", {}).get("items", [])
                if items_list:
                    item_id = str(items_list[0].get("item_id", ""))
                    nombre = " ".join((items_list[0].get("item_name") or "").strip().split())
            except (ValueError, KeyError):
                pass

        if not item_id:
            # Fallback: extract ID from the product-image class e.g. product-image-90712
            for cls_token in product_el.get("class", []):
                if cls_token.startswith("product-image-"):
                    item_id = cls_token.replace("product-image-", "")
                    break

        if not nombre:
            title_el = product_el.find("h2", class_="product-title")
            if title_el:
                nombre = " ".join(title_el.get_text(separator=" ", strip=True).split())

        if not nombre or len(nombre) < 3 or len(nombre) > 500:
            continue
        if _is_non_food(nombre):
            continue

        # Deduplicate by item_id
        if item_id and item_id in seen_ids:
            continue
        if item_id:
            seen_ids.add(item_id)

        # --- Offer price ---
        price_now_el = product_el.find("span", class_="price-offer-now")
        if not price_now_el:
            continue
        precio_oferta = _parse_price(price_now_el.get_text(strip=True))
        if precio_oferta is None or precio_oferta <= 0:
            continue
        if precio_original <= precio_oferta:
            continue

        # --- Product URL ---
        # Use product-title-link anchor (most reliable — always present)
        link_el = product_el.find("a", class_="product-title-link")
        if link_el is None:
            link_el = product_el.find("a", class_="actionZoom")
        producto_url: str | None = None
        if link_el:
            href = link_el.get("href", "")
            if href:
                # Normalize: remove :443 port
                href = href.replace(":443", "")
                if href.startswith("http"):
                    producto_url = href
                else:
                    producto_url = f"{_FAMILIA_BASE}{href}"

        # --- Image URL ---
        img_el = product_el.find("img", class_="product-img")
        imagen_url: str | None = None
        if img_el:
            src = img_el.get("src", "")
            if src:
                if src.startswith("http"):
                    imagen_url = src
                else:
                    imagen_url = f"{_FAMILIA_BASE}{src}"

        descuento = _calculate_discount(precio_original, precio_oferta)

        offers.append(
            OfertaCreate(
                producto_nombre=nombre,
                precio_original=precio_original,
                precio_oferta=precio_oferta,
                descuento_porcentaje=descuento,
                imagen_url=imagen_url,
                producto_url=producto_url,
                fuente=_FAMILIA_FUENTE,
                activo=True,
            )
        )

    return offers


async def scrape_familia() -> list[OfertaCreate]:
    """Scrape Familia Online for genuine food price-drop offers.

    Uses the publicly accessible category pages (as Googlebot, which is
    allowed by robots.txt). Fetches the sitemap to discover all category URLs,
    then scrapes each standard numeric category for products where the original
    (before) price is explicitly shown alongside the current offer price.

    Caps at _FAMILIA_MAX_CATEGORIES to keep scrape time under ~6 minutes.
    """
    try:
        from bs4 import BeautifulSoup  # noqa: F401 — validate early
    except ImportError:
        logger.error("beautifulsoup4 not installed — run: pip install beautifulsoup4 lxml")
        return []

    all_offers: list[OfertaCreate] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True, timeout=_REQUEST_TIMEOUT) as client:
        # --- Step 1: Fetch sitemap ---
        logger.info("Familia Online: fetching sitemap")
        try:
            sitemap_resp = await client.get(_FAMILIA_SITEMAP_URL, headers=_FAMILIA_HEADERS)
            sitemap_resp.raise_for_status()
            sitemap_xml = sitemap_resp.text
        except Exception as exc:
            logger.error("Familia Online: sitemap fetch failed: %s", exc)
            return []

        # Extract all /es/supermercado/ category URLs
        category_urls: list[str] = re.findall(
            r"<loc>(https://www\.familiaonline\.es/es/supermercado/[^<]+)</loc>",
            sitemap_xml,
        )
        logger.info("Familia Online: found %d category URLs in sitemap", len(category_urls))

        # Filter to standard numeric category paths only
        filtered = [
            url for url in category_urls
            if _familia_is_standard_category(
                url.replace("https://www.familiaonline.es/es/supermercado/", "")
            )
        ]
        logger.info(
            "Familia Online: %d standard category URLs after filtering",
            len(filtered),
        )

        # Cap to avoid excessively long scrapes
        if len(filtered) > _FAMILIA_MAX_CATEGORIES:
            filtered = filtered[:_FAMILIA_MAX_CATEGORIES]
            logger.info("Familia Online: capped to %d categories", _FAMILIA_MAX_CATEGORIES)

        # --- Step 2: Scrape each category ---
        total_parsed = 0
        for idx, url in enumerate(filtered):
            try:
                resp = await client.get(url, headers=_FAMILIA_HEADERS, timeout=_REQUEST_TIMEOUT)
                if resp.status_code != 200 or "login" in str(resp.url):
                    logger.debug("Familia Online: skipping %s (blocked or login redirect)", url)
                    await asyncio.sleep(_FAMILIA_DELAY)
                    continue

                page_offers = _familia_extract_products(resp.text)
                total_parsed += len(page_offers)

                new_count = 0
                for offer in page_offers:
                    # Deduplicate by product URL (most reliable) or product name
                    key = offer.producto_url or offer.producto_nombre
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    all_offers.append(offer)
                    new_count += 1

                if new_count > 0:
                    cat_name = url.rstrip("/").split("/")[-1]
                    logger.debug(
                        "Familia Online [%d/%d] %s: %d offers parsed, %d new",
                        idx + 1, len(filtered), cat_name, len(page_offers), new_count,
                    )

            except Exception as exc:
                logger.warning("Familia Online: error scraping %s: %s", url, exc)

            await asyncio.sleep(_FAMILIA_DELAY)

        logger.info(
            "Familia Online scrape complete: %d price-drop offers from %d parsed "
            "(scraped %d/%d categories)",
            len(all_offers), total_parsed, len(filtered), len(category_urls),
        )

    return all_offers


# ---------------------------------------------------------------------------
# Gadis scraping (Gadisline catalog API strategy)
# ---------------------------------------------------------------------------
#
# Gadis operates an online store at gadisline.com powered by a Next.js frontend
# that calls a JSON catalog API at catalog.gadisline.com.
#
# Strategy:
#   POST https://catalog.gadisline.com/api/v3/catalog/products/search
#        ?page_number=N&rows_per_page=50&keep_request=false&sort_type=asc
#   Body: {"minimum_should_match":1,"embedded_search":{"has_offers":true}}
#   Headers: store-id and site-id (static UUIDs tied to the Galicia warehouse)
#
# The API returns all products with active promotions. Gadis uses a "DIPTYCH"
# (Tienes Buen Ojo) promotion model where the discounted price is already
# applied at product level. No original/before price is exposed by the API.
# precio_original is stored as None (same as Alcampo and Aldi scrapers).
#
# Pagination: total_pages in the response "page" object, 50 rows/page.
# Typical yield: ~500-600 promotional products per scrape.
# ---------------------------------------------------------------------------

_GADIS_FUENTE = "www.gadisline.com"
_GADIS_CATALOG_URL = (
    "https://catalog.gadisline.com/api/v3/catalog/products/search"
)
_GADIS_BASE_URL = "https://www.gadisline.com"
_GADIS_STORE_ID = "891d5c1e-a7a0-4287-9ea3-30c5703a4f63"
_GADIS_SITE_ID  = "56df88f9-479f-4361-891e-e1864dba1ca3"
_GADIS_ROWS_PER_PAGE = 50
_GADIS_DELAY = 0.5
_GADIS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.gadisline.com",
    "Referer": "https://www.gadisline.com/precios-especiales",
    "accept-language": "ES",
    "time-zone": "Europe/Madrid",
    "store-id": _GADIS_STORE_ID,
    "site-id": _GADIS_SITE_ID,
}
_GADIS_SEARCH_BODY = {
    "minimum_should_match": 1,
    "embedded_search": {
        "has_offers": True,
    },
}


def _gadis_product_to_oferta(product: dict) -> OfertaCreate | None:
    """Convert a Gadisline catalog product dict to OfertaCreate.

    Returns None if the product lacks a name, a valid price, or if the offers
    array is empty (guard against the API returning non-promo items).
    """
    # Name: take the ES language description
    descriptions = product.get("commercial_description") or []
    nombre = ""
    for d in descriptions:
        if d.get("language") == "ES":
            nombre = d.get("value", "").strip()
            break
    if not nombre:
        nombre = (descriptions[0].get("value", "") if descriptions else "").strip()

    if not nombre or len(nombre) < 3 or len(nombre) > 400:
        return None

    if _is_non_food(nombre):
        return None

    # Only include products that actually have an offer
    if not product.get("offers"):
        return None

    # Price — already the discounted price; no original price available
    precio_oferta = product.get("price")
    if precio_oferta is None:
        return None
    try:
        precio_oferta = float(precio_oferta)
    except (ValueError, TypeError):
        return None
    if precio_oferta <= 0:
        return None

    # Image URL — use thumbnail for smaller payload
    imagen_url: str | None = None
    image_data = product.get("image") or {}
    imagen_url = image_data.get("image_thumbnails") or image_data.get("image")

    # Product URL — slug is relative (e.g. "/chorizo-de-cantimpalos-...")
    slug = product.get("slug") or ""
    producto_url: str | None = None
    if slug:
        producto_url = f"{_GADIS_BASE_URL}{slug}" if slug.startswith("/") else f"{_GADIS_BASE_URL}/{slug}"

    return OfertaCreate(
        producto_nombre=nombre,
        precio_original=None,       # not available from this API
        precio_oferta=precio_oferta,
        descuento_porcentaje=None,  # no original price → cannot calculate
        imagen_url=imagen_url,
        producto_url=producto_url,
        fuente=_GADIS_FUENTE,
        activo=True,
    )


async def scrape_gadis() -> list[OfertaCreate]:
    """Scrape Gadisline precios especiales via the catalog JSON API.

    Paginates through all pages with has_offers=true filter. Returns all
    food promotional products found. precio_original is None because the
    API only exposes the discounted price; no before-price is available.
    """
    all_offers: list[OfertaCreate] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(follow_redirects=True, timeout=_REQUEST_TIMEOUT) as client:
        page_number = 0
        total_pages = 1  # will be updated after first response

        while page_number < total_pages:
            params = {
                "page_number": page_number,
                "rows_per_page": _GADIS_ROWS_PER_PAGE,
                "keep_request": "false",
                "sort_type": "asc",
            }
            try:
                resp = await client.post(
                    _GADIS_CATALOG_URL,
                    params=params,
                    headers=_GADIS_HEADERS,
                    json=_GADIS_SEARCH_BODY,
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("Gadis: request failed at page %d: %s", page_number, exc)
                break

            page_meta = data.get("page") or {}
            total_pages = page_meta.get("total_pages", 1)
            elements = data.get("elements") or []

            if not elements:
                break

            new_count = 0
            for product in elements:
                oferta = _gadis_product_to_oferta(product)
                if oferta is None:
                    continue
                key = oferta.producto_url or oferta.producto_nombre
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                all_offers.append(oferta)
                new_count += 1

            logger.info(
                "Gadis page %d/%d: %d products, %d new food offers (total: %d)",
                page_number + 1, total_pages, len(elements), new_count, len(all_offers),
            )

            page_number += 1
            await asyncio.sleep(_GADIS_DELAY)

    logger.info("Gadis scrape complete: %d promotional food offers", len(all_offers))
    return all_offers


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

async def save_offers(
    offers: list[OfertaCreate],
    fuente: str,
    db: AsyncSession,
) -> tuple[int, int, int]:
    """Upsert scraped offers. Returns (saved, duplicates_skipped, deactivated)."""
    repo = OfertaRepository(db)

    deactivated = await repo.deactivate_by_fuente(fuente)
    logger.info("Deactivated %d previous offers from %s", deactivated, fuente)

    saved = 0
    duplicates = 0

    for offer_data in offers:
        existing = None
        if offer_data.producto_url:
            existing = await repo.get_by_url_and_fuente(offer_data.producto_url, fuente)

        if existing is not None:
            existing.producto_nombre = offer_data.producto_nombre
            existing.precio_original = offer_data.precio_original
            existing.precio_oferta = offer_data.precio_oferta
            existing.descuento_porcentaje = offer_data.descuento_porcentaje
            existing.imagen_url = offer_data.imagen_url
            existing.activo = True
            from datetime import datetime, timezone
            existing.scraped_at = datetime.now(timezone.utc)
            await db.flush()
            duplicates += 1
        else:
            await repo.create(offer_data)
            saved += 1

    # Take a snapshot of current data for this fuente after upsert
    try:
        from src.db.repositories.snapshot_repository import SnapshotRepository
        snap_repo = SnapshotRepository(db)
        await snap_repo.create_from_live_data(fuente)
        logger.info("Snapshot created for %s", fuente)
    except Exception as exc:
        logger.warning("Snapshot creation failed for %s (non-fatal): %s", fuente, exc)

    return saved, duplicates, deactivated


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

async def list_ofertas(
    db: AsyncSession,
    fuente: str | None = None,
    activo: bool | None = None,
    barcode: str | None = None,
    q: str | None = None,
    sort: str = "descuento_desc",
    offset: int = 0,
    limit: int = 20,
) -> tuple[list, int]:
    repo = OfertaRepository(db)
    return await repo.get_all(fuente=fuente, activo=activo, barcode=barcode, q=q, sort=sort, offset=offset, limit=limit)


async def get_oferta(oferta_id: int, db: AsyncSession):
    repo = OfertaRepository(db)
    return await repo.get(oferta_id)


async def get_ofertas_by_barcode(barcode: str, db: AsyncSession) -> list:
    repo = OfertaRepository(db)
    return await repo.get_by_barcode(barcode)


async def list_fuentes(db: AsyncSession) -> list[str]:
    repo = OfertaRepository(db)
    return await repo.get_fuentes()


async def compare_product(q: str, db: AsyncSession, limit: int = 40) -> dict:
    repo = OfertaRepository(db)
    results = await repo.get_for_compare(q, limit)
    return {
        "query": q,
        "total": len(results),
        "best": results[0] if results else None,
        "results": results,
    }


async def get_stats(db: AsyncSession) -> dict:
    repo = OfertaRepository(db)
    return await repo.get_stats()


async def delete_fuente(fuente: str, db: AsyncSession) -> int:
    repo = OfertaRepository(db)
    count = await repo.delete_by_fuente(fuente)
    await db.commit()
    return count


# ---------------------------------------------------------------------------
# Barcode enrichment (name-similarity matching against api_label catalog)
# ---------------------------------------------------------------------------

_ENRICH_THRESHOLD = 0.65  # Conservative — only high-confidence automatic matches
_ENRICH_TIMEOUT = 5.0


def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


async def enrich_barcodes_from_label(db: AsyncSession) -> dict:
    """Fetch api_label products with barcodes, match against offers by name similarity,
    and update matching offers with their EAN barcode.

    Returns a stats dict: {matched, candidates, offers_checked}.
    """
    from src.core.config import settings

    # 1. Fetch api_label catalog (products with barcodes)
    catalog: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=_ENRICH_TIMEOUT) as client:
            resp = await client.get(f"{settings.LABEL_API_URL}/api/v1/internal/products")
            if resp.status_code == 200:
                catalog = resp.json()
    except Exception as exc:
        logger.warning("enrich_barcodes: could not reach api_label: %s", exc)
        return {"matched": 0, "candidates": 0, "offers_checked": 0}

    if not catalog:
        logger.info("enrich_barcodes: no products with barcode in api_label catalog")
        return {"matched": 0, "candidates": 0, "offers_checked": 0}

    # 2. Load api_offer offers without barcode
    repo = OfertaRepository(db)
    offers = await repo.get_without_barcode()

    if not offers:
        logger.info("enrich_barcodes: all offers already have barcodes")
        return {"matched": 0, "candidates": 0, "offers_checked": 0}

    logger.info(
        "enrich_barcodes: %d catalog products, %d offers to check",
        len(catalog),
        len(offers),
    )

    # 3. For each offer, find the best matching catalog product above threshold
    updates: list[tuple[int, str]] = []
    for offer in offers:
        best_score = 0.0
        best_barcode: str | None = None
        for product in catalog:
            label_name = product["name"] + (" " + product["brand"] if product.get("brand") else "")
            score = _similarity(label_name, offer.producto_nombre)
            if score > best_score:
                best_score = score
                best_barcode = product["barcode"]
        if best_score >= _ENRICH_THRESHOLD and best_barcode:
            updates.append((offer.id, best_barcode))

    if updates:
        matched = await repo.bulk_update_barcodes(updates)
        await db.commit()
        logger.info("enrich_barcodes: updated %d offers with barcodes", matched)
    else:
        matched = 0
        logger.info("enrich_barcodes: no matches above threshold %.2f", _ENRICH_THRESHOLD)

    return {
        "matched": matched,
        "candidates": len(updates),
        "offers_checked": len(offers),
    }


async def cleanup_stale_offers(db: AsyncSession, stale_hours: int | None = None) -> dict:
    """Deactivate offers whose scraped_at is older than stale_hours.

    Returns {fuente: count_deactivated} for each affected source.
    """
    if stale_hours is None:
        from src.core.config import settings
        stale_hours = settings.OFFER_STALE_HOURS

    repo = OfertaRepository(db)
    stale_counts = await repo.deactivate_stale(stale_hours)

    if stale_counts:
        total = sum(stale_counts.values())
        logger.info(
            "Stale cleanup: deactivated %d offers older than %dh — %s",
            total,
            stale_hours,
            stale_counts,
        )
    else:
        logger.debug("Stale cleanup: no stale offers found (threshold: %dh)", stale_hours)

    return stale_counts


async def run_stale_cleanup_background() -> None:
    """Standalone cleanup coroutine — creates its own DB session. For startup/BackgroundTasks."""
    from src.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            result = await cleanup_stale_offers(db)
            if result:
                await db.commit()
        except Exception as exc:
            logger.error("Background stale cleanup failed: %s", exc)


async def run_enrich_background() -> None:
    """Standalone enrichment coroutine — creates its own DB session. For BackgroundTasks."""
    from src.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            stats = await enrich_barcodes_from_label(db)
            logger.info("Background enrichment complete: %s", stats)
        except Exception as exc:
            logger.error("Background enrichment failed: %s", exc)


# ---------------------------------------------------------------------------
# Evolucion (price evolution snapshots)
# ---------------------------------------------------------------------------

async def get_evolucion(
    db: AsyncSession,
    days: int = 7,
    fuente: str | None = None,
) -> dict:
    """Return time-series snapshot data for the evolution charts."""
    from src.db.repositories.snapshot_repository import SnapshotRepository
    snap_repo = SnapshotRepository(db)
    series = await snap_repo.get_time_series(days=days, fuente=fuente)
    fuentes = sorted({row["fuente"] for row in series})
    return {
        "days": days,
        "fuentes": fuentes,
        "series": series,
    }
