from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.colores.schemas import ColorResponse
from app.domains.imagenes.schemas import ImagenDetail
from app.domains.skus.schemas import SkuDetail
from app.shared.services.validators import validator_boolean


class ProductoColorCreate(BaseModel):
    producto_id: UUID = Field(...)
    color_id: UUID = Field(...)
    is_visible: bool = Field(default=True)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": False,
            }
        },
    )


class ProductoColorUpdate(BaseModel):
    """producto_id es la foreign key de dueño y no se modifica."""

    color_id: UUID | None = Field(default=None)
    is_visible: bool | None = Field(default=None)

    @field_validator("color_id")
    @classmethod
    def validate_color_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("El color no puede ser null.")
        return value

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": True,
            }
        },
    )


class ProductoColorResponse(BaseModel):
    id: UUID
    producto_id: UUID
    color_id: UUID
    is_visible: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": True,
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class ProductoColorResponseAudit(ProductoColorResponse):
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
                "producto_id": "55555555-5555-4555-8555-555555555555",
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": True,
                "created_at": "2026-10-29T14:30:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-10-29T15:00:00Z",
                "updated_by": "22222222-2222-4222-8222-222222222222",
                "is_deleted": False,
                "deleted_at": None,
                "deleted_by": None,
            }
        },
    )


class ProductoColorListItem(ProductoColorResponse):
    """color es referencia y se embebe; producto_id es dueño y queda como id."""

    color: ColorResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ProductoColorResponse.model_json_schema()["example"],
                "color": ColorResponse.model_json_schema()["example"],
            }
        },
    )


class ProductoColorDetail(ProductoColorListItem):
    """Añade sus hijos propios: imágenes y SKUs."""

    imagenes: list[ImagenDetail]
    skus: list[SkuDetail]

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **ProductoColorListItem.model_json_schema()["example"],
                "imagenes": [ImagenDetail.model_json_schema()["example"]],
                "skus": [SkuDetail.model_json_schema()["example"]],
            }
        },
    )
