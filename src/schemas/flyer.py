"""Pydantic schemas for flyer (folleto) PDF extraction."""

from pydantic import BaseModel


class FlyerProduct(BaseModel):
    producto_nombre: str
    precio_oferta: float | None = None
    precio_original: float | None = None
    descuento_porcentaje: float | None = None


class FlyerPreviewResponse(BaseModel):
    page: int
    products: list[FlyerProduct]
    estimated_cost_usd: float
    raw_response: str | None = None
