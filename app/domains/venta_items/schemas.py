"""
Los ítems no tienen rutas propias: se crean con POST /ventas/ y se reemplazan
con PUT /ventas/{id}/items mientras la venta está pendiente. Por eso solo hay
un schema de entrada y uno de respuesta.
"""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.shared.services.validators import (
    validator_non_negative_integer,
    validator_non_negative_money,
)


class VentaItemCreate(BaseModel):
    """
    Lo que envía el cliente por cada ítem. Los precios, el subtotal y el
    snapshot (producto, color, talla y código de barras) los calcula el service
    a partir del SKU.
    """

    sku_id: UUID = Field(...)
    cantidad: int = Field(..., gt=0)
    descuento_unitario: Decimal = Field(default=Decimal("0"), max_digits=12, decimal_places=2)

    @field_validator("sku_id")
    @classmethod
    def validate_sku_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("El SKU no puede ser null.")
        return value

    @field_validator("cantidad", mode="before")
    @classmethod
    def validate_cantidad(cls, value: object) -> int:
        if value is None:
            raise ValueError("La cantidad no puede ser null.")
        # El tipo lo valida el validador compartido; gt=0 descarta luego el cero.
        return validator_non_negative_integer(value)

    @field_validator("descuento_unitario", mode="before")
    @classmethod
    def validate_descuento_unitario(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("El descuento no puede ser null; usa 0 si no hay descuento.")
        return validator_non_negative_money(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "sku_id": "44444444-4444-4444-8444-444444444444",
                "cantidad": 2,
                "descuento_unitario": 0,
            }
        },
    )


class VentaItemResponse(BaseModel):
    id: UUID
    sku_id: UUID
    cantidad: int
    precio_normal: Decimal
    precio_unitario: Decimal
    descuento_unitario: Decimal
    subtotal: Decimal
    producto_nombre: str
    color_nombre: str
    talla_etiqueta: str
    codigo_barras: str | None

    @field_serializer(
        "precio_normal",
        "precio_unitario",
        "descuento_unitario",
        "subtotal",
        when_used="json",
    )
    def serialize_money(self, value: Decimal) -> float:
        # Igual que los precios de los SKUs: la API expone los importes como números JSON.
        return float(value)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "55555555-5555-4555-8555-555555555555",
                "sku_id": "44444444-4444-4444-8444-444444444444",
                "cantidad": 2,
                "precio_normal": 29.95,
                "precio_unitario": 19.95,
                "descuento_unitario": 0,
                "subtotal": 39.9,
                "producto_nombre": "Camisa Oxford",
                "color_nombre": "Azul marino",
                "talla_etiqueta": "M",
                "codigo_barras": "8412345678905",
            }
        },
    )
