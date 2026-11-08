from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field, Relationship

from app.core.base_model import BaseModel
from app.domains.secciones.models import Seccion


class Categoria(BaseModel, table=True):
    __tablename__ = "categorias"
    __table_args__ = (
        Index("categorias_idx_categorias_parent", "parent_id"),
        Index("categorias_idx_categorias_seccion", "seccion_id"),
        # El nombre (su slug) es único entre hermanas. Son dos índices porque
        # PostgreSQL trata cada NULL como distinto: las raíces (parent_id NULL)
        # se comparan dentro de su sección y las subcategorías, dentro de su padre.
        Index(
            "uq_categorias_raiz_slug",
            "seccion_id",
            "slug",
            unique=True,
            postgresql_where=text("parent_id IS NULL AND is_deleted = false"),
        ),
        Index(
            "uq_categorias_hermanas_slug",
            "parent_id",
            "slug",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL AND is_deleted = false"),
        ),
        {"schema": "public"},
    )

    seccion_id: UUID = Field(foreign_key="public.secciones.id", nullable=False)
    parent_id: UUID | None = Field(default=None, foreign_key="public.categorias.id", nullable=True)
    nombre: str = Field(max_length=100, nullable=False)
    slug: str = Field(max_length=120, nullable=False)
    is_visible: bool = Field(default=True, nullable=False)

    seccion: Seccion = Relationship(sa_relationship_kwargs={"lazy": "raise"})
