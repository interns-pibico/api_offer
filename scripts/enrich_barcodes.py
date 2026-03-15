"""Enrich api_offer offers with EAN barcodes from api_label products.

Matches by product name similarity (difflib). Shows all candidates above
the threshold for review before applying any changes.

Usage:
    /home/erpnext/api_offer_env/bin/python scripts/enrich_barcodes.py

Options:
    --threshold 0.5   Minimum similarity score to consider a match (default 0.45)
    --apply           Apply updates without asking for confirmation per match
    --dry-run         Show matches but never write to DB
"""

import asyncio
import os
import re
import sys
from difflib import SequenceMatcher

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

LABEL_URL = os.environ.get("LABEL_DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/api_label_psql")
OFFER_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/api_offer_psql")

DEFAULT_THRESHOLD = 0.45
DRY_RUN  = "--dry-run" in sys.argv
APPLY_ALL = "--apply" in sys.argv

# Parse optional --threshold N
THRESHOLD = DEFAULT_THRESHOLD
for i, arg in enumerate(sys.argv):
    if arg == "--threshold" and i + 1 < len(sys.argv):
        try:
            THRESHOLD = float(sys.argv[i + 1])
        except ValueError:
            pass

# ANSI colors
G = "\033[32m"; Y = "\033[33m"; R = "\033[31m"; B = "\033[34m"; RESET = "\033[0m"; BOLD = "\033[1m"


def normalize(name: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


async def main():
    label_engine = create_async_engine(LABEL_URL, echo=False)
    offer_engine  = create_async_engine(OFFER_URL, echo=False)

    label_sf = async_sessionmaker(label_engine, class_=AsyncSession, expire_on_commit=False)
    offer_sf  = async_sessionmaker(offer_engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Load api_label products with barcode
    async with label_sf() as db:
        rows = await db.execute(
            text("SELECT name, brand, barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''")
        )
        label_products = [
            {"name": r.name, "brand": r.brand or "", "barcode": r.barcode}
            for r in rows.fetchall()
        ]

    if not label_products:
        print(f"{Y}No hay productos con barcode en api_label.{RESET}")
        await label_engine.dispose()
        await offer_engine.dispose()
        return

    print(f"{B}{BOLD}Productos con barcode en api_label:{RESET} {len(label_products)}")
    for p in label_products:
        print(f"  • {p['name']!r:40s}  EAN: {p['barcode']}")

    # 2. Load api_offer offers with barcode=NULL
    async with offer_sf() as db:
        rows = await db.execute(
            text("SELECT id, producto_nombre, fuente FROM ofertas WHERE barcode IS NULL ORDER BY fuente, producto_nombre")
        )
        offers = [{"id": r.id, "nombre": r.producto_nombre, "fuente": r.fuente} for r in rows.fetchall()]

    print(f"\n{B}{BOLD}Ofertas sin barcode en api_offer:{RESET} {len(offers)}")
    print(f"{B}Umbral de similitud:{RESET} {THRESHOLD}\n")

    # 3. For each label product, find best matching offers
    candidates: list[dict] = []
    for lp in label_products:
        label_name = lp["name"] + (" " + lp["brand"] if lp["brand"] else "")
        for o in offers:
            score = similarity(label_name, o["nombre"])
            if score >= THRESHOLD:
                candidates.append({
                    "offer_id":    o["id"],
                    "offer_name":  o["nombre"],
                    "fuente":      o["fuente"],
                    "label_name":  lp["name"],
                    "barcode":     lp["barcode"],
                    "score":       score,
                })

    if not candidates:
        print(f"{Y}No se encontraron coincidencias con umbral {THRESHOLD}.{RESET}")
        print(f"Prueba con un umbral más bajo:  --threshold 0.3")
        await label_engine.dispose()
        await offer_engine.dispose()
        return

    # Sort by score desc
    candidates.sort(key=lambda x: x["score"], reverse=True)

    print(f"{G}{BOLD}Coincidencias encontradas: {len(candidates)}{RESET}\n")
    print(f"{'SCORE':>6}  {'OFERTA (api_offer)':<50}  {'PRODUCTO (api_label)':<30}  {'EAN'}")
    print("─" * 110)
    for c in candidates:
        color = G if c["score"] >= 0.65 else Y if c["score"] >= 0.5 else ""
        print(f"{color}{c['score']:>6.2f}  {c['offer_name'][:50]:<50}  {c['label_name'][:30]:<30}  {c['barcode']}{RESET}")

    if DRY_RUN:
        print(f"\n{Y}--dry-run: no se ha escrito nada.{RESET}")
        await label_engine.dispose()
        await offer_engine.dispose()
        return

    # 4. Apply updates
    print()
    if not APPLY_ALL:
        resp = input(f"{BOLD}¿Aplicar todas estas vinculaciones? [s/N]: {RESET}").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            await label_engine.dispose()
            await offer_engine.dispose()
            return

    updated = 0
    async with offer_sf() as db:
        for c in candidates:
            await db.execute(
                text("UPDATE ofertas SET barcode = :barcode WHERE id = :id AND barcode IS NULL"),
                {"barcode": c["barcode"], "id": c["offer_id"]},
            )
            updated += 1
        await db.commit()

    print(f"\n{G}{BOLD}✓ {updated} ofertas actualizadas con barcode.{RESET}")

    await label_engine.dispose()
    await offer_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
