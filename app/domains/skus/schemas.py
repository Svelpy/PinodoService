from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.domains.tallas.schemas import TallaResponse
from app.shared.services.validators import (
    validator_barcode,
    validator_boolean,
    validator_date,
    validator_non_negative_integer,
    validator_positive_money,
)


class SkuPrecio(BaseModel):
    """Contenido del JSONB precio. Se usa tanto en la entrada como en la respuesta."""

    normal: Decimal = Field(..., max_digits=10, decimal_places=2)
    rebajado: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    rebaja_hasta: date | None = Field(default=None)

    @field_validator("normal", mode="before")
    @classmethod
    def validate_normal(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("El precio normal no puede ser null.")
        return validator_positive_money(value)

    @field_validator("rebajado", mode="before")
    @classmethod
    def validate_rebajado(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return validator_positive_money(value)

    @field_validator("rebaja_hasta", mode="before")
    @classmethod
    def validate_rebaja_hasta(cls, value: object) -> date | None:
        if value is None:
            return None
        return validator_date(value)

    @model_validator(mode="after")
    def validate_rebaja(self) -> "SkuPrecio":
        if self.rebajado is not None and self.rebajado >= self.normal:
            raise ValueError("El precio rebajado debe ser menor que el precio normal.")
        if self.rebaja_hasta is not None and self.rebajado is None:
            raise ValueError("rebaja_hasta solo puede indicarse junto con un precio rebajado.")
        return self

    @field_serializer("normal", "rebajado", when_used="json")
    def serialize_money(self, value: Decimal | None) -> float | None:
        # JSONB y la API guardan y exponen los importes como números JSON.
        return None if value is None else float(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "normal": 29.95,
                "rebajado": 19.95,
                "rebaja_hasta": "2026-12-31",
            }
        },
    )


class SkuStockInput(BaseModel):
    """Stock que envía el cliente. La fecha actualizado la asigna el service."""

    cantidad: int = Field(default=0, ge=0)
    minimo: int = Field(default=0, ge=0)

    @field_validator("cantidad", "minimo", mode="before")
    @classmethod
    def validate_non_negative(cls, value: object) -> int:
        if value is None:
            raise ValueError("El valor de stock no puede ser null.")
        return validator_non_negative_integer(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "cantidad": 12,
                "minimo": 3,
            }
        },
    )


class SkuStock(BaseModel):
    """Contenido del JSONB stock tal como se expone en la respuesta."""

    cantidad: int
    minimo: int
    actualizado: datetime | None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "cantidad": 12,
                "minimo": 3,
                "actualizado": "2026-10-29T15:00:00Z",
            }
        },
    )


class SkuCreate(BaseModel):
    producto_color_id: UUID = Field(...)
    talla_id: UUID = Field(...)
    codigo_barras: str | None = Field(default=None, min_length=1, max_length=50)
    is_visible: bool = Field(default=True)
    precio: SkuPrecio = Field(...)
    stock: SkuStockInput = Field(default_factory=SkuStockInput)

    @field_validator("codigo_barras", mode="before")
    @classmethod
    def validate_codigo_barras(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_barcode(value)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    @field_validator("stock", mode="before")
    @classmethod
    def validate_stock(cls, value: object) -> object:
        if value is None:
            raise ValueError("El stock no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": None, "rebaja_hasta": None},
                "stock": {"cantidad": 12, "minimo": 3},
            }
        },
    )


class SkuUpdate(BaseModel):
    """
    producto_color_id es la foreign key de dueño y no se modifica.

    precio y stock se reemplazan completos cuando se envían.
    """

    talla_id: UUID | None = Field(default=None)
    codigo_barras: str | None = Field(default=None, min_length=1, max_length=50)
    is_visible: bool | None = Field(default=None)
    precio: SkuPrecio | None = Field(default=None)
    stock: SkuStockInput | None = Field(default=None)

    @field_validator("talla_id")
    @classmethod
    def validate_talla_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("La talla no puede ser null.")
        return value

    @field_validator("codigo_barras", mode="before")
    @classmethod
    def validate_codigo_barras(cls, value: object) -> str | None:
        if value is None:
            return None
        return validator_barcode(value)

    @field_validator("is_visible", mode="before")
    @classmethod
    def validate_is_visible(cls, value: object) -> bool:
        if value is None:
            raise ValueError("La visibilidad no puede ser null.")
        return validator_boolean(value)

    @field_validator("precio", mode="before")
    @classmethod
    def validate_precio(cls, value: object) -> object:
        if value is None:
            raise ValueError("El precio no puede ser null.")
        return value

    @field_validator("stock", mode="before")
    @classmethod
    def validate_stock(cls, value: object) -> object:
        if value is None:
            raise ValueError("El stock no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "stock": {"cantidad": 20, "minimo": 3},
            }
        },
    )


class SkuResponse(BaseModel):
    id: UUID
    producto_color_id: UUID
    talla_id: UUID
    codigo_barras: str | None
    is_visible: bool
    precio: SkuPrecio
    stock: SkuStock
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "11111111-1111-4111-8111-111111111111",
                "producto_color_id": "88888888-8888-4888-8888-888888888888",
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "stock": {"cantidad": 12, "minimo": 3, "actualizado": "2026-10-29T15:00:00Z"},
                "created_at": "2026-10-29T14:30:00Z",
                "updated_at": "2026-10-29T15:00:00Z",
            }
        },
    )


class SkuResponseAudit(SkuResponse):
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
                "talla_id": "99999999-9999-4999-8999-999999999999",
                "codigo_barras": "8412345678905",
                "is_visible": True,
                "precio": {"normal": 29.95, "rebajado": 19.95, "rebaja_hasta": "2026-12-31"},
                "stock": {"cantidad": 12, "minimo": 3, "actualizado": "2026-10-29T15:00:00Z"},
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


class SkuListItem(SkuResponse):
    """talla es referencia y se embebe; producto_color_id es dueño y queda como id."""

    talla: TallaResponse

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **SkuResponse.model_json_schema()["example"],
                "talla": TallaResponse.model_json_schema()["example"],
            }
        },
    )


class SkuDetail(SkuListItem):
    """Sin hijos propios: no añade campos respecto a SkuListItem."""
