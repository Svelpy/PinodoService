from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import TipoImagen


class ImagenCreate(BaseModel):
    """
    Datos que acompañan al archivo subido.

    La url no se recibe: el service la asigna tras subir el archivo a Cloudinary.
    """

    producto_color_id: UUID = Field(...)
    tipo: TipoImagen = Field(default=TipoImagen.MODELO)

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, value: TipoImagen | None) -> TipoImagen:
        if value is None:
            raise ValueError("El tipo de imagen no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "tipo": "MODELO",
            }
        },
    )


class ImagenUpdate(BaseModel):
    """
    producto_color_id es la foreign key de dueño y no se modifica.

    Para reemplazar el archivo se elimina la imagen y se sube una nueva.
    """

    tipo: TipoImagen | None = Field(default=None)

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, value: TipoImagen | None) -> TipoImagen:
        if value is None:
            raise ValueError("El tipo de imagen no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "tipo": "DETALLE",
            }
        },
    )


class ImagenResponse(BaseModel):
    id: UUID
    producto_color_id: UUID
    url: str
    tipo: TipoImagen
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "url": "https://res.cloudinary.com/demo/image/upload/camisa-oxford-azul.jpg",
                "tipo": "MODELO",
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class ImagenResponseAudit(ImagenResponse):
    created_by: UUID | None
    updated_by: UUID | None
    is_deleted: bool
    deleted_at: datetime | None
    deleted_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "url": "https://res.cloudinary.com/demo/image/upload/camisa-oxford-azul.jpg",
                "tipo": "MODELO",
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": True,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
            }
        },
    )


class ImagenListItem(ImagenResponse):
    """Sin referencias que embeber: producto_color_id es la foreign key de dueño."""


class ImagenDetail(ImagenListItem):
    """Sin hijos propios: no añade campos respecto a ImagenListItem."""
