from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class Seccion(BaseModel, table=True):
    __tablename__ = "secciones"
    __table_args__ = (
        Index(
            "uq_secciones_slug",
            "slug",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    nombre: str = Field(max_length=100, nullable=False)
    slug: str = Field(max_length=120, nullable=False)
    is_visible: bool = Field(default=True, nullable=False)
