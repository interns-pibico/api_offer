"""Script to migrate offers from api_label_psql to api_offer_psql.

Usage:
    cd /home/erpnext/.services/api_offer
    /home/erpnext/api_offer_env/bin/python scripts/migrate_offers.py

Migrates all rows from api_label's ofertas table to api_offer's ofertas table.
Sets barcode=NULL for all migrated rows (barcode didn't exist in api_label).
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SOURCE_URL = os.environ.get("SOURCE_DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/api_label_psql")
DEST_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/api_offer_psql")


async def migrate():
    src_engine = create_async_engine(SOURCE_URL, echo=False)
    dst_engine = create_async_engine(DEST_URL, echo=False)

    src_session_factory = async_sessionmaker(src_engine, class_=AsyncSession, expire_on_commit=False)
    dst_session_factory = async_sessionmaker(dst_engine, class_=AsyncSession, expire_on_commit=False)

    async with src_session_factory() as src_db:
        result = await src_db.execute(
            text(
                "SELECT producto_nombre, precio_original, precio_oferta, "
                "descuento_porcentaje, imagen_url, producto_url, fuente, "
                "scraped_at, activo FROM ofertas"
            )
        )
        rows = result.fetchall()
        logger.info("Found %d rows in source api_label_psql.ofertas", len(rows))

    async with dst_session_factory() as dst_db:
        # Clear existing data
        await dst_db.execute(text("TRUNCATE TABLE ofertas RESTART IDENTITY"))
        await dst_db.commit()
        logger.info("Truncated destination table")

        count = 0
        for row in rows:
            await dst_db.execute(
                text(
                    "INSERT INTO ofertas "
                    "(barcode, producto_nombre, precio_original, precio_oferta, "
                    "descuento_porcentaje, imagen_url, producto_url, fuente, scraped_at, activo) "
                    "VALUES (NULL, :nombre, :orig, :oferta, :desc, :img, :url, :fuente, :scraped_at, :activo)"
                ),
                {
                    "nombre": row.producto_nombre,
                    "orig": row.precio_original,
                    "oferta": row.precio_oferta,
                    "desc": row.descuento_porcentaje,
                    "img": row.imagen_url,
                    "url": row.producto_url,
                    "fuente": row.fuente,
                    "scraped_at": row.scraped_at or datetime.now(timezone.utc),
                    "activo": row.activo,
                },
            )
            count += 1

        await dst_db.commit()
        logger.info("Migrated %d offers to api_offer_psql.ofertas", count)

    await src_engine.dispose()
    await dst_engine.dispose()
    logger.info("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
