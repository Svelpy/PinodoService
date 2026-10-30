from uuid import UUID

from sqlalchemy import Index, Text
from sqlmodel import Field

from app.core.base_model import BaseModel


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
