from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.snapshot import OfferSnapshot
from src.models.oferta import Oferta


class SnapshotRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_from_live_data(self, fuente: str) -> OfferSnapshot:
        result = await self.db.execute(
            select(
                func.count().label("total"),
                func.min(Oferta.precio_oferta).label("precio_min"),
                func.avg(Oferta.precio_oferta).label("precio_avg"),
                func.max(Oferta.precio_oferta).label("precio_max"),
                func.avg(Oferta.descuento_porcentaje).label("descuento_avg"),
                func.max(Oferta.descuento_porcentaje).label("descuento_max"),
            ).where(Oferta.fuente == fuente, Oferta.activo == True)
        )
        row = result.one()
        snapshot = OfferSnapshot(
            fuente=fuente,
            snapped_at=datetime.now(timezone.utc),
            total_activas=row.total,
            precio_min=row.precio_min,
            precio_avg=row.precio_avg,
            precio_max=row.precio_max,
            descuento_avg=row.descuento_avg,
            descuento_max=row.descuento_max,
        )
        self.db.add(snapshot)
        return snapshot

    async def get_time_series(self, days: int, fuente: Optional[str] = None) -> list[dict]:
        base_sql = (
            "SELECT"
            "  date_trunc('day', snapped_at) AS day,"
            "  fuente,"
            "  round(avg(total_activas))::integer AS total_activas,"
            "  round(avg(descuento_avg)::numeric, 2) AS descuento_avg,"
            "  round(avg(descuento_max)::numeric, 2) AS descuento_max,"
            "  round(avg(precio_avg)::numeric, 2) AS precio_avg"
            " FROM offer_snapshots"
            f" WHERE snapped_at >= now() - INTERVAL '{days} days'"
        )

        if fuente is not None:
            sql = base_sql + " AND fuente = :fuente GROUP BY day, fuente ORDER BY day ASC"
            result = await self.db.execute(text(sql), {"fuente": fuente})
        else:
            sql = base_sql + " GROUP BY day, fuente ORDER BY day ASC"
            result = await self.db.execute(text(sql))

        rows = result.mappings().all()
        return [
            {
                "day": row["day"].isoformat(),
                "fuente": row["fuente"],
                "total_activas": row["total_activas"],
                "descuento_avg": float(row["descuento_avg"]) if row["descuento_avg"] else None,
                "descuento_max": float(row["descuento_max"]) if row["descuento_max"] else None,
                "precio_avg": float(row["precio_avg"]) if row["precio_avg"] else None,
            }
            for row in rows
        ]
