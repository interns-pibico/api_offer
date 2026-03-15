from typing import Optional
from pydantic import BaseModel


class SnapshotOut(BaseModel):
    day: str
    fuente: str
    total_activas: int
    descuento_avg: Optional[float] = None
    descuento_max: Optional[float] = None
    precio_avg: Optional[float] = None


class EvolucionResponse(BaseModel):
    days: int
    fuentes: list[str]
    series: list[SnapshotOut]
