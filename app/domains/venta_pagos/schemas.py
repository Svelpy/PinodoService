"""
Un pago se registra y no se anula: la devolución se hace cancelando la venta
completa. Por eso no hay DELETE, y PATCH solo cambia la referencia; el monto y
el método no se corrigen. El comprobante se sube con su propio endpoint.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.shared.enums import MetodoPago
from app.shared.services.validators import validator_non_empty_text, validator_positive_money

MAX_PAGOS_POR_VENTA = 10


def _validate_referencia(value: object) -> str | None:
    if value is None:
        return None
    return validator_non_empty_text(value)


class VentaPagoDetailCreate(BaseModel):
    """
    Pago enviado junto con su venta (POST /ventas/ o al confirmarla), sin
    venta_id: lo asigna el service. monto es lo aplicado a la venta; en
    efectivo no incluye el vuelto.
    """

    metodo: MetodoPago = Field(...)
    monto: Decimal = Field(..., max_digits=12, decimal_places=2)
    referencia: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("metodo")
    @classmethod
    def validate_metodo(cls, value: MetodoPago | None) -> MetodoPago:
        if value is None:
            raise ValueError("El método de pago no puede ser null.")
        return value

    @field_validator("monto", mode="before")
    @classmethod
    def validate_monto(cls, value: object) -> Decimal:
        if value is None:
            raise ValueError("El monto no puede ser null.")
        return validator_positive_money(value)

    @field_validator("referencia", mode="before")
    @classmethod
    def validate_referencia(cls, value: object) -> str | None:
        return _validate_referencia(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "metodo": "QR",
                "monto": 150,
                "referencia": "0048213",
            }
        },
    )


class VentaPagoCreate(VentaPagoDetailCreate):
    """Entrada de POST /venta-pagos/: un pago más para una venta pendiente."""

    venta_id: UUID = Field(...)

    @field_validator("venta_id")
    @classmethod
    def validate_venta_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("La venta no puede ser null.")
        return value

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                **VentaPagoDetailCreate.model_config["json_schema_extra"]["example"],
                "venta_id": "66666666-6666-4666-8666-666666666666",
            }
        },
    )


class VentaPagoUpdate(BaseModel):
    """Entrada de PATCH /venta-pagos/{id}. referencia acepta null para quitarla."""

    referencia: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("referencia", mode="before")
    @classmethod
    def validate_referencia(cls, value: object) -> str | None:
        return _validate_referencia(value)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"referencia": "0048213"}},
    )


class VentaPagoResponse(BaseModel):
    """created_by es quien recibió el pago: es un dato de negocio, no solo de auditoría."""

    id: UUID
    venta_id: UUID
    metodo: MetodoPago
    monto: Decimal
    referencia: str | None
    comprobante_url: str | None
    created_at: datetime
    created_by: UUID | None
    updated_at: datetime

    @field_serializer("monto", when_used="json")
    def serialize_money(self, value: Decimal) -> float:
        # Igual que las ventas: la API expone los importes como números JSON.
        return float(value)

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "99999999-9999-4999-8999-999999999999",
                "venta_id": "66666666-6666-4666-8666-666666666666",
                "metodo": "QR",
                "monto": 150,
                "referencia": "0048213",
                "comprobante_url": "https://res.cloudinary.com/demo/image/upload/v1/pinodo/comprobantes/abc123.jpg",
                "created_at": "2026-11-07T14:35:00Z",
                "created_by": "22222222-2222-4222-8222-222222222222",
                "updated_at": "2026-11-07T14:40:00Z",
            }
        },
    )


class VentaPagoResponseAudit(VentaPagoResponse):
    """Un pago nunca se elimina, así que solo añade quién hizo el último cambio."""

    updated_by: UUID | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                **VentaPagoResponse.model_config["json_schema_extra"]["example"],
                "updated_by": "33333333-3333-4333-8333-333333333333",
            }
        },
    )


class VentaPagoListItem(VentaPagoResponse):
    """venta_id es su foreign key de dueño: no se embebe. No tiene referencias."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": VentaPagoResponse.model_config["json_schema_extra"]["example"]},
    )


class VentaPagoDetail(VentaPagoListItem):
    """Un pago no tiene hijos: el Detail es igual al ListItem."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": VentaPagoResponse.model_config["json_schema_extra"]["example"]},
    )
