"""Pydantic schemas for Oferta (scraped price-drop offers)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OfertaCreate(BaseModel):
    barcode: str | None = None
    producto_nombre: str
    precio_original: float | None = None
    precio_oferta: float | None = None
    descuento_porcentaje: float | None = None
    imagen_url: str | None = None
    producto_url: str | None = None
    fuente: str
    categoria: str | None = None
    activo: bool = True


class OfertaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    barcode: str | None
    producto_nombre: str
    precio_original: float | None
    precio_oferta: float | None
    descuento_porcentaje: float | None
    imagen_url: str | None
    producto_url: str | None
    fuente: str
    categoria: str | None = None
    nutriscore: str | None = None
    novascore: int | None = None
    scraped_at: datetime
    activo: bool


class CompareResponse(BaseModel):
    query: str
    total: int
    best: OfertaResponse | None
    results: list[OfertaResponse]


class ScrapeResponse(BaseModel):
    total_found: int
    saved: int
    duplicates_skipped: int
    deactivated_previous: int
    source: str
