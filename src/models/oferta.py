"""Oferta model — scraped price-drop offers from external sources."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Oferta(Base):
    __tablename__ = "ofertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    producto_nombre: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    precio_original: Mapped[float | None] = mapped_column(Float, nullable=True)
    precio_oferta: Mapped[float | None] = mapped_column(Float, nullable=True)
    descuento_porcentaje: Mapped[float | None] = mapped_column(Float, nullable=True)
    imagen_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    producto_url: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    fuente: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    categoria: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    nutriscore: Mapped[str | None] = mapped_column(String(1), nullable=True, index=True)
    novascore: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
