from uuid import UUID

from sqlalchemy import Index, Text, and_
from sqlmodel import Field, Relationship

from app.core.base_model import BaseModel
from app.domains.categoria_productos.models import CategoriaProducto
from app.domains.categorias.models import Categoria
from app.domains.producto_colores.models import ProductoColor
from app.domains.secciones.models import Seccion


class Producto(BaseModel, table=True):
    __tablename__ = "productos"
    __table_args__ = (
        Index("productos_idx_productos_seccion", "seccion_id"),
        {"schema": "public"},
    )

    seccion_id: UUID = Field(foreign_key="public.secciones.id", nullable=False)
    nombre: str = Field(max_length=200, nullable=False)
    descripcion: str | None = Field(default=None, sa_type=Text, nullable=True)
    cuidados: str | None = Field(default=None, sa_type=Text, nullable=True)
    composicion: str | None = Field(default=None, sa_type=Text, nullable=True)
    is_visible: bool = Field(default=True, nullable=False)

    seccion: Seccion = Relationship(sa_relationship_kwargs={"lazy": "raise"})
    colores: list[ProductoColor] = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise",
            "order_by": "(ProductoColor.created_at, ProductoColor.id)",
        }
    )
    # N:M de solo lectura a través de los enlaces activos, en el orden en que se
    # asignaron; las asignaciones se gestionan con PUT /productos/{id}/categorias
    # (AGENTS.md §9).
    categorias: list[Categoria] = Relationship(
        sa_relationship_kwargs={
            "lazy": "raise",
            "secondary": CategoriaProducto.__table__,
            "primaryjoin": lambda: and_(
                Producto.id == CategoriaProducto.producto_id,
                CategoriaProducto.is_deleted.is_(False),
            ),
            "secondaryjoin": lambda: Categoria.id == CategoriaProducto.categoria_id,
            "order_by": lambda: (CategoriaProducto.created_at, CategoriaProducto.id),
            "viewonly": True,
        }
    )
