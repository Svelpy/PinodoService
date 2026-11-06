from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domains.colores.schemas import ColorResponse
from app.domains.imagenes.schemas import ImagenDetail, ImagenDetailCreate
from app.domains.skus.schemas import SkuDetail, SkuDetailCreate
from app.shared.services.validators import validator_boolean


class ProductoColorDetailCreate(BaseModel):
    """
    Color con sus hijos propios (imágenes y SKUs), para crearlo en un solo paso.

    Se usa dentro de ProductoDetailCreate, sin producto_id porque lo asigna el
    service al crear el producto, y como base de ProductoColorCreate.
    """

    color_id: UUID = Field(...)
    is_visible: bool = Field(default=True)
    imagenes: list[ImagenDetailCreate] = Field(default_factory=list, max_length=30)
    skus: list[SkuDetailCreate] = Field(default_factory=list, max_length=50)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    @field_validator("imagenes", "skus", mode="before")
    @classmethod
    def validate_lists(cls, value: object) -> object:
        if value is None:
            raise ValueError("La lista no puede ser null; usa [] si no hay elementos.")
        return value

    @field_validator("imagenes")
    @classmethod
    def validate_urls_unicas(cls, value: list[ImagenDetailCreate]) -> list[ImagenDetailCreate]:
        urls = [imagen.url for imagen in value]
        if len(urls) != len(set(urls)):
            raise ValueError("Una imagen no puede repetirse dentro del mismo color.")
        return value

    @field_validator("skus")
    @classmethod
    def validate_tallas_unicas(cls, value: list[SkuDetailCreate]) -> list[SkuDetailCreate]:
        talla_ids = [sku.talla_id for sku in value]
        if len(talla_ids) != len(set(talla_ids)):
            raise ValueError("Una talla no puede repetirse dentro del mismo color.")
        codigos = [sku.codigo_barras for sku in value if sku.codigo_barras is not None]
        if len(codigos) != len(set(codigos)):
            raise ValueError("Un código de barras no puede repetirse dentro del mismo color.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": True,
                "imagenes": [ImagenDetailCreate.model_config["json_schema_extra"]["example"]],
                "skus": [SkuDetailCreate.model_config["json_schema_extra"]["example"]],
            }
        },
    )


class ProductoColorCreate(ProductoColorDetailCreate):
    """
    Entrada de POST /producto-colores/: añade a un producto existente un color
    con sus imágenes y SKUs, en una transacción. Sin imagenes ni skus crea solo
    el color.
    """

    producto_id: UUID = Field(...)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                **ProductoColorDetailCreate.model_config["json_schema_extra"]["example"],
                "producto_id": "55555555-5555-4555-8555-555555555555",
            }
        },
    )


class ProductoColorUpdate(BaseModel):
    """
    Solo cambia la visibilidad. producto_id es la foreign key de dueño y no se
    modifica; color_id tampoco, porque cambiarlo reescribiría lo que
    representan sus imágenes, sus SKUs y, cuando existan, sus ventas. Un color
    equivocado se elimina y se vuelve a crear.
    """

    is_visible: bool | None = Field(default=None)

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
                "is_visible": False,
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
                "is_deleted": True,
                "deleted_at": "2026-10-30T09:00:00Z",
                "deleted_by": "22222222-2222-4222-8222-222222222222",
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
