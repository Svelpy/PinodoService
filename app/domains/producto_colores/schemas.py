from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.colores.schemas import ColorResponse
from app.domains.imagenes.schemas import ImagenDetail, ImagenDetailCreate
from app.domains.skus.schemas import SkuDetail, SkuDetailCreate, SkuDetailUpdate
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
    Edita el color con sus imágenes y SKUs, con el mismo body que
    ProductoColorDetailCreate para que el frontend reutilice el formulario de
    creación. Lo que se omite no cambia.

    - color_id: corrige la etiqueta del color (por ejemplo, Azul por Azul
      marino) sin tocar sus imágenes, SKUs ni stock. Las ventas conservan el
      nombre que copiaron al venderse. El producto no puede tener ya ese color.
      producto_id es la foreign key de dueño y no se envía.
    - imagenes: reemplaza la galería, emparejando por url. Conserva las que
      siguen (actualizando su tipo), elimina las que faltan y añade las nuevas,
      que se suben antes con POST /imagenes/uploads. [] quita todas.
    - skus: filas de la tabla de tallas (ver SkuDetailUpdate). Con id se
      actualizan y sin id se crean. Un SKU que no se envía no cambia.
    - sku_ids_eliminar: SKUs del color que se eliminan. Es la única forma de
      quitar una talla aquí, para que una lista incompleta no borre nada.
    """

    color_id: UUID | None = Field(default=None)
    is_visible: bool | None = Field(default=None)
    imagenes: list[ImagenDetailCreate] | None = Field(default=None, max_length=30)
    skus: list[SkuDetailUpdate] | None = Field(default=None, max_length=50)
    sku_ids_eliminar: list[UUID] | None = Field(default=None, max_length=50)

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

    @field_validator("imagenes", "skus", "sku_ids_eliminar", mode="before")
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
    def validate_skus_unicos(cls, value: list[SkuDetailUpdate]) -> list[SkuDetailUpdate]:
        ids = [sku.id for sku in value if sku.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Un SKU no puede repetirse dentro del mismo color.")
        talla_ids = [sku.talla_id for sku in value]
        if len(talla_ids) != len(set(talla_ids)):
            raise ValueError("Una talla no puede repetirse dentro del mismo color.")
        codigos = [sku.codigo_barras for sku in value if sku.codigo_barras is not None]
        if len(codigos) != len(set(codigos)):
            raise ValueError("Un código de barras no puede repetirse dentro del mismo color.")
        return value

    @field_validator("sku_ids_eliminar")
    @classmethod
    def remove_duplicate_ids(cls, value: list[UUID]) -> list[UUID]:
        # Se conserva la primera aparición.
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_sin_editar_y_eliminar(self) -> "ProductoColorUpdate":
        editados = {sku.id for sku in self.skus or [] if sku.id is not None}
        if editados & set(self.sku_ids_eliminar or []):
            raise ValueError("Un SKU no puede editarse y eliminarse en la misma petición.")
        return self

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "color_id": "77777777-7777-4777-8777-777777777777",
                "is_visible": True,
                "imagenes": [ImagenDetailCreate.model_config["json_schema_extra"]["example"]],
                "skus": [
                    SkuDetailUpdate.model_config["json_schema_extra"]["example"],
                    {
                        **SkuDetailCreate.model_config["json_schema_extra"]["example"],
                        "talla_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                        "codigo_barras": "8412345678912",
                    },
                ],
                "sku_ids_eliminar": ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"],
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
