from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class CategoriaProducto(BaseModel, table=True):
    __tablename__ = "categoria_productos"
    __table_args__ = (
        Index("categoria_productos_idx_catprod_producto", "producto_id"),
        Index(
            "uq_categoria_productos",
            "categoria_id",
            "producto_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    categoria_id: UUID = Field(foreign_key="public.categorias.id", nullable=False)
    producto_id: UUID = Field(foreign_key="public.productos.id", nullable=False)
