from typing import Any
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.core.base_model import BaseModel


def default_precio() -> dict[str, Any]:
    return {"normal": 0, "rebajado": None, "rebaja_hasta": None}


def default_stock() -> dict[str, Any]:
    return {"cantidad": 0, "minimo": 0, "actualizado": None}


class Sku(BaseModel, table=True):
    __tablename__ = "skus"
    __table_args__ = (
        Index("skus_idx_skus_talla", "talla_id"),
        Index(
            "uq_skus_color_talla",
            "producto_color_id",
            "talla_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_skus_codigo_barras",
            "codigo_barras",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    producto_color_id: UUID = Field(foreign_key="public.producto_colores.id",nullable=False)
    talla_id: UUID = Field(foreign_key="public.tallas.id", nullable=False)
    codigo_barras: str | None = Field(default=None, max_length=50, nullable=True)
    is_visible: bool = Field(default=True, nullable=False)
    precio: dict[str, Any] = Field(default_factory=default_precio,sa_type=JSONB,nullable=False)
    stock: dict[str, Any] = Field(default_factory=default_stock,sa_type=JSONB,nullable=False)
