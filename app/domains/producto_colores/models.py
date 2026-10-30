from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class ProductoColor(BaseModel, table=True):
    __tablename__ = "producto_colores"
    __table_args__ = (
        Index("producto_colores_idx_prodcolor_producto", "producto_id"),
        Index(
            "uq_producto_colores_producto_color",
            "producto_id",
            "color_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    producto_id: UUID = Field(foreign_key="public.productos.id", nullable=False)
    color_id: UUID = Field(foreign_key="public.colores.id", nullable=False)
    is_visible: bool = Field(default=True, nullable=False)
