from sqlalchemy import Index, text
from sqlmodel import Field

from app.core.base_model import BaseModel


class Talla(BaseModel, table=True):
    __tablename__ = "tallas"
    __table_args__ = (
        Index(
            "uq_tallas_etiqueta",
            "etiqueta",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        {"schema": "public"},
    )

    etiqueta: str = Field(max_length=30, nullable=False)
