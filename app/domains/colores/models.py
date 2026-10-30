from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class Color(BaseModel, table=True):
    __tablename__ = "colores"
    __table_args__ = (
        Index(
            "uq_colores_nombre",
            "nombre",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    nombre: str = Field(max_length=60, nullable=False)
    codigo_hex: str = Field(max_length=7, nullable=False)
