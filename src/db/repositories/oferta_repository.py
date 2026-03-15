"""Repository for Oferta model — price-drop offers."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.oferta import Oferta
from src.schemas.oferta import OfertaCreate


class OfertaRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, oferta_id: int) -> Oferta | None:
        result = await self.db.execute(select(Oferta).where(Oferta.id == oferta_id))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        fuente: str | None = None,
        activo: bool | None = None,
        barcode: str | None = None,
        q: str | None = None,
        sort: str = "descuento_desc",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Oferta], int]:
        query = select(Oferta)
        count_query = select(func.count()).select_from(Oferta)

        if fuente is not None:
            query = query.where(Oferta.fuente == fuente)
            count_query = count_query.where(Oferta.fuente == fuente)
        if activo is not None:
            query = query.where(Oferta.activo == activo)
            count_query = count_query.where(Oferta.activo == activo)
        if barcode is not None:
            query = query.where(Oferta.barcode == barcode)
            count_query = count_query.where(Oferta.barcode == barcode)
        if q is not None:
            like = f"%{q}%"
            query = query.where(Oferta.producto_nombre.ilike(like))
            count_query = count_query.where(Oferta.producto_nombre.ilike(like))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar_one()

        if sort == "precio_asc":
            order = Oferta.precio_oferta.asc().nulls_last()
        elif sort == "precio_desc":
            order = Oferta.precio_oferta.desc().nulls_last()
        elif sort == "fecha_desc":
            order = Oferta.scraped_at.desc()
        else:  # descuento_desc (default)
            order = Oferta.descuento_porcentaje.desc().nulls_last()

        query = query.order_by(order).offset(offset).limit(limit)
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        return items, total

    async def get_by_barcode(self, barcode: str) -> list[Oferta]:
        result = await self.db.execute(
            select(Oferta)
            .where(Oferta.barcode == barcode, Oferta.activo == True)  # noqa: E712
            .order_by(Oferta.descuento_porcentaje.desc().nulls_last())
        )
        return list(result.scalars().all())

    async def get_fuentes(self) -> list[str]:
        result = await self.db.execute(
            select(Oferta.fuente).distinct().order_by(Oferta.fuente)
        )
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        total_result = await self.db.execute(
            select(func.count()).select_from(Oferta).where(Oferta.activo == True)  # noqa: E712
        )
        total = total_result.scalar_one()

        fuentes_result = await self.db.execute(
            select(func.count(Oferta.fuente.distinct())).where(Oferta.activo == True)  # noqa: E712
        )
        fuentes_count = fuentes_result.scalar_one()

        avg_result = await self.db.execute(
            select(func.avg(Oferta.descuento_porcentaje)).where(
                Oferta.activo == True, Oferta.descuento_porcentaje.isnot(None)  # noqa: E712
            )
        )
        avg_discount = avg_result.scalar_one()

        return {
            "total_ofertas": total,
            "fuentes": fuentes_count,
            "descuento_medio": round(float(avg_discount), 1) if avg_discount else 0.0,
        }

    async def get_by_url_and_fuente(self, producto_url: str, fuente: str) -> Oferta | None:
        result = await self.db.execute(
            select(Oferta).where(
                Oferta.producto_url == producto_url,
                Oferta.fuente == fuente,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, data: OfertaCreate) -> Oferta:
        oferta = Oferta(**data.model_dump())
        self.db.add(oferta)
        await self.db.flush()
        await self.db.refresh(oferta)
        return oferta

    async def deactivate_by_fuente(self, fuente: str) -> int:
        result = await self.db.execute(
            update(Oferta)
            .where(Oferta.fuente == fuente, Oferta.activo == True)  # noqa: E712
            .values(activo=False)
        )
        await self.db.flush()
        return result.rowcount

    async def deactivate_stale(self, stale_hours: int) -> dict[str, int]:
        """Mark active offers as inactive if their scraped_at is older than
        *stale_hours* hours ago.  Returns a dict of {fuente: count_deactivated}."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)

        # Find which fuentes have stale active offers (for logging)
        stale_query = (
            select(Oferta.fuente, func.count())
            .where(Oferta.activo == True, Oferta.scraped_at < cutoff)  # noqa: E712
            .group_by(Oferta.fuente)
        )
        result = await self.db.execute(stale_query)
        stale_counts = {row[0]: row[1] for row in result.fetchall()}

        if not stale_counts:
            return {}

        # Bulk deactivate
        await self.db.execute(
            update(Oferta)
            .where(Oferta.activo == True, Oferta.scraped_at < cutoff)  # noqa: E712
            .values(activo=False)
        )
        await self.db.flush()
        return stale_counts

    async def get_for_compare(self, q: str, limit: int = 40) -> list[Oferta]:
        result = await self.db.execute(
            select(Oferta)
            .where(Oferta.activo == True, Oferta.producto_nombre.ilike(f"%{q}%"))  # noqa: E712
            .order_by(Oferta.precio_oferta.asc().nulls_last())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_without_barcode(self) -> list[Oferta]:
        """Return active offers that have no barcode set (candidates for enrichment)."""
        result = await self.db.execute(
            select(Oferta).where(Oferta.activo == True, Oferta.barcode.is_(None))  # noqa: E712
        )
        return list(result.scalars().all())

    async def bulk_update_barcodes(self, updates: list[tuple[int, str]]) -> int:
        """Set barcode on offers that currently have barcode=NULL. Returns count updated."""
        if not updates:
            return 0
        count = 0
        for offer_id, barcode in updates:
            result = await self.db.execute(
                update(Oferta)
                .where(Oferta.id == offer_id, Oferta.barcode.is_(None))
                .values(barcode=barcode)
            )
            count += result.rowcount
        await self.db.flush()
        return count

    async def delete_by_fuente(self, fuente: str) -> int:
        from sqlalchemy import delete
        result = await self.db.execute(
            delete(Oferta).where(Oferta.fuente == fuente)
        )
        await self.db.flush()
        return result.rowcount
