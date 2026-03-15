from datetime import datetime
from sqlalchemy import Column, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import TIMESTAMP

from src.db.session import Base


class OfferSnapshot(Base):
    __tablename__ = "offer_snapshots"

    id = Column(Integer, primary_key=True)
    fuente = Column(String(255), nullable=False)
    snapped_at = Column(TIMESTAMP(timezone=True), nullable=False)
    total_activas = Column(Integer, nullable=False)
    precio_min = Column(Float, nullable=True)
    precio_avg = Column(Float, nullable=True)
    precio_max = Column(Float, nullable=True)
    descuento_avg = Column(Float, nullable=True)
    descuento_max = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_offer_snapshots_fuente", "fuente"),
        Index("ix_offer_snapshots_snapped_at", "snapped_at"),
    )
