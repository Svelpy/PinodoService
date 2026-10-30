from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class Categoria(BaseModel, table=True):
    __tablename__ = "categorias"
    __table_args__ = (
        Index("categorias_idx_categorias_parent", "parent_id"),
        Index("categorias_idx_categorias_seccion", "seccion_id"),
        Index(
            "uq_categorias_slug",
            "slug",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    seccion_id: UUID = Field(foreign_key="public.secciones.id", nullable=False)
    parent_id: UUID | None = Field(default=None, foreign_key="public.categorias.id", nullable=True)
    nombre: str = Field(max_length=100, nullable=False)
    slug: str = Field(max_length=120, nullable=False)
    is_visible: bool = Field(default=True, nullable=False)
