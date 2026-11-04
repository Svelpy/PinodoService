from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import TipoImagen
from app.shared.services.validators import validator_http_url


class ImagenDetailCreate(BaseModel):
    """
    Imagen ya subida con POST /imagenes/uploads, para asociarla a un color.

    Se usa dentro de ProductoColorDetailCreate, sin producto_color_id porque lo
    asigna el service al crear el color, y como base de ImagenCreate. El
    service comprueba que la url sea una subida del proyecto y que no esté ya
    asociada a otra imagen.
    """

    url: str = Field(..., min_length=1, max_length=500)
    tipo: TipoImagen = Field(default=TipoImagen.MODELO)

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: object) -> str:
        if value is None:
            raise ValueError("La url de la imagen no puede ser null.")
        return validator_http_url(value)

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
                "url": (
                    "https://res.cloudinary.com/demo/image/upload/v1730700000/"
                    "pinodo/imagenes/k3j9x2camisa.jpg"
                ),
                "tipo": "MODELO",
            }
        },
    )


class ImagenCreate(ImagenDetailCreate):
    """
    Entrada de POST /imagenes/: asocia a un color existente una imagen ya
    subida con POST /imagenes/uploads.
    """

    producto_color_id: UUID = Field(...)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                **ImagenDetailCreate.model_config["json_schema_extra"]["example"],
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
            }
        },
    )


class ImagenUploadResponse(BaseModel):
    """
    Imagen subida a Cloudinary que todavía no pertenece a ningún color.

    La url se envía después en el create del producto, que es quien crea el
    registro de la imagen.
    """

    url: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": (
                    "https://res.cloudinary.com/demo/image/upload/v1730700000/"
                    "pinodo/imagenes/k3j9x2camisa.jpg"
                ),
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


class ImagenBibliotecaItem(ImagenResponse):
    """
    Imagen con el producto y el color a los que pertenece, para la biblioteca.

    Schema especial de lectura: a diferencia de ImagenListItem, muestra datos
    del dueño. Son campos planos y no embebidos, porque imagenes no puede
    importar los schemas de productos sin crear un ciclo de imports.
    """

    producto_id: UUID
    producto_nombre: str
    color_id: UUID
    color_nombre: str
    color_codigo_hex: str

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ImagenResponse.model_config["json_schema_extra"]["example"],
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "producto_nombre": "Camisa Oxford",
                "color_id": "77777777-7777-4777-8777-777777777777",
                "color_nombre": "Azul marino",
                "color_codigo_hex": "#1E3A8A",
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
