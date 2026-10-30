from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.base_model import utc_now


class Config(SQLModel, table=True):
    """Configuración de la tienda: una sola fila con id = 1, sin BaseModel."""

    __tablename__ = "config"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_fila_unica"),
        {"schema": "public"},
    )

    id: int = Field(default=1, primary_key=True, sa_column_kwargs={"autoincrement": False})
    nombre_tienda: str = Field(max_length=150, nullable=False)
    descripcion: str | None = Field(default=None, sa_type=Text, nullable=True)
    logo_url: str | None = Field(default=None, max_length=500, nullable=True)
    favicon_url: str | None = Field(default=None, max_length=500, nullable=True)
    email_contacto: str | None = Field(default=None, max_length=255, nullable=True)
    telefono: str | None = Field(default=None, max_length=30, nullable=True)
    whatsapp: str | None = Field(default=None, max_length=30, nullable=True)
    direccion: str | None = Field(default=None, max_length=255, nullable=True)
    map_url: str | None = Field(default=None, max_length=500, nullable=True)
    ciudad: str | None = Field(default=None, max_length=100, nullable=True)

    horario: dict[str, Any] = Field(default_factory=dict,sa_type=JSONB,nullable=False)
    redes_sociales: dict[str, Any] = Field(default_factory=dict,sa_type=JSONB,nullable=False)

    en_mantenimiento: bool = Field(default=False, nullable=False)

    updated_at: datetime = Field(default_factory=utc_now,sa_type=DateTime(timezone=True),nullable=False)
    updated_by: UUID | None = Field(default=None, nullable=True)
